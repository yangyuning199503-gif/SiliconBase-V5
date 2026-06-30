#!/usr/bin/env python3
"""
长期任务管理工具 - 供 AI 创建、管理3槽位长期任务

功能：
- 创建长期任务到指定槽位
- 暂停/恢复槽位任务
- 查询槽位状态
- 修改槽位任务参数

作者: SiliconBase V5
日期: 2026-04-09
"""
import asyncio
from typing import Any

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error


class CreateLongTask(BaseTool):
    """
    创建长期任务到3槽位面板

    在指定的槽位（1、2、3）创建一个长时间运行的任务。
    长期任务支持暂停/恢复、进度追踪、断点续传。
    """
    tool_id = "create_long_task"
    name = "创建长期任务"
    description = (
        "在3槽位长期任务面板中创建一个长时间运行的任务。\\n"
        "支持暂停/恢复、进度追踪、断点续传。\\n"
        "槽位ID必须是1、2或3。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "slot_id": {
                "type": "integer",
                "enum": [1, 2, 3],
                "description": "槽位ID（1、2、3）"
            },
            "task_name": {
                "type": "string",
                "description": "任务名称"
            },
            "task_type": {
                "type": "string",
                "description": "任务类型标识"
            },
            "params": {
                "type": "object",
                "description": "任务参数"
            },
            "user_requirements": {
                "type": "string",
                "description": "用户需求描述（用于恢复时确认）"
            },
            "timeout": {
                "type": "integer",
                "description": "任务超时时间（秒），默认3600"
            }
        },
        "required": ["slot_id", "task_name", "task_type"]
    }

    def _execute(self, **kwargs) -> dict:
        slot_id = kwargs.get("slot_id")
        task_name = kwargs.get("task_name")
        task_type = kwargs.get("task_type")
        params = kwargs.get("params", {})
        user_requirements = kwargs.get("user_requirements", "")
        timeout = kwargs.get("timeout", 3600)

        # 参数验证
        if slot_id not in [1, 2, 3]:
            return format_error(INVALID_PARAMS, detail="slot_id必须是1、2或3")

        if not task_name or not isinstance(task_name, str):
            return format_error(INVALID_PARAMS, detail="task_name必须是有效的字符串")

        try:
            from core.task.long_task_slots import get_long_task_slots
            slots_manager = get_long_task_slots()

            # 检查槽位是否被占用
            current_task = slots_manager.get_slot_status(slot_id)
            if current_task and current_task.status.value not in ["idle", "completed", "error"]:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"槽位{slot_id}当前被任务'{current_task.task_name}'占用，请先取消或等待完成"
                )

            # 创建任务配置
            task_config = {
                "task_name": task_name,
                "task_type": task_type,
                "params": params,
                "user_requirements": user_requirements,
                "timeout": timeout
            }

            # 创建任务
            task_id = slots_manager.create_task(
                slot_id=slot_id,
                task_config=task_config
            )

            # 获取创建的任务对象
            task = slots_manager.get_slot_status(slot_id)

            return {
                "success": True,
                "error_code": None,
                "user_message": (
                    f"长任务 '{task_name}' 已创建！\\n"
                    f"槽位: {slot_id}\\n"
                    f"任务ID: {task_id}\\n"
                    f"状态: {task.status.value if task else 'unknown'}"
                ),
                "data": {
                    "task_id": task_id,
                    "slot_id": slot_id,
                    "task_name": task_name,
                    "status": task.status.value if task else 'unknown'
                }
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"创建长任务失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class PauseLongTask(BaseTool):
    """暂停指定槽位的长期任务"""
    tool_id = "pause_long_task"
    name = "暂停长期任务"
    description = "暂停指定槽位（1、2、3）中正在运行的长任务"
    input_schema = {
        "type": "object",
        "properties": {
            "slot_id": {
                "type": "integer",
                "enum": [1, 2, 3],
                "description": "槽位ID（1、2、3）"
            },
            "reason": {
                "type": "string",
                "description": "暂停原因"
            }
        },
        "required": ["slot_id"]
    }

    def _execute(self, **kwargs) -> dict:
        slot_id = kwargs.get("slot_id")
        reason = kwargs.get("reason", "用户请求暂停")

        if slot_id not in [1, 2, 3]:
            return format_error(INVALID_PARAMS, detail="slot_id必须是1、2或3")

        try:
            from core.task.long_task_slots import get_long_task_slots
            slots_manager = get_long_task_slots()

            task = slots_manager.get_slot_status(slot_id)
            if not task:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"槽位{slot_id}没有任务")

            success = slots_manager.pause_task(slot_id, reason=reason)

            if success:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"槽位{slot_id}的任务 '{task.task_name}' 已暂停",
                    "data": {
                        "slot_id": slot_id,
                        "task_id": task.task_id,
                        "status": "paused"
                    }
                }
            else:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"暂停失败，当前状态: {task.status.value}"
                )

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"暂停任务失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class ResumeLongTask(BaseTool):
    """恢复指定槽位的长期任务"""
    tool_id = "resume_long_task"
    name = "恢复长期任务"
    description = "恢复指定槽位（1、2、3）中已暂停的长任务"
    input_schema = {
        "type": "object",
        "properties": {
            "slot_id": {
                "type": "integer",
                "enum": [1, 2, 3],
                "description": "槽位ID（1、2、3）"
            },
            "ai_understanding": {
                "type": "string",
                "description": "AI对需求的理解确认（恢复时需要）"
            }
        },
        "required": ["slot_id", "ai_understanding"]
    }

    def _execute(self, **kwargs) -> dict:
        slot_id = kwargs.get("slot_id")
        ai_understanding = kwargs.get("ai_understanding", "")

        if slot_id not in [1, 2, 3]:
            return format_error(INVALID_PARAMS, detail="slot_id必须是1、2或3")

        if not ai_understanding:
            return format_error(INVALID_PARAMS, detail="恢复长任务时必须提供ai_understanding确认理解")

        try:
            from core.task.long_task_slots import get_long_task_slots
            slots_manager = get_long_task_slots()

            task = slots_manager.get_slot_status(slot_id)
            if not task:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"槽位{slot_id}没有任务")

            # 提交AI理解确认
            slots_manager.update_ai_understanding(slot_id, ai_understanding)

            # 恢复任务
            success = slots_manager.resume_task(slot_id)

            if success:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"槽位{slot_id}的任务 '{task.task_name}' 已恢复",
                    "data": {
                        "slot_id": slot_id,
                        "task_id": task.task_id,
                        "status": "running"
                    }
                }
            else:
                return format_error(
                    TOOL_EXECUTION_ERROR,
                    detail=f"恢复失败，当前状态: {task.status.value}"
                )

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"恢复任务失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class GetLongTaskStatus(BaseTool):
    """获取3槽位长期任务状态"""
    tool_id = "get_long_task_status"
    name = "获取长期任务状态"
    description = "查询3槽位长任务面板的当前状态，包括各槽位的任务信息和进度"
    input_schema = {
        "type": "object",
        "properties": {
            "slot_id": {
                "type": "integer",
                "enum": [1, 2, 3],
                "description": "指定槽位ID（可选，不提供则返回所有槽位）"
            }
        }
    }

    def _execute(self, **kwargs) -> dict:
        slot_id = kwargs.get("slot_id")

        try:
            from core.task.long_task_slots import get_long_task_slots
            slots_manager = get_long_task_slots()

            if slot_id:
                # 获取指定槽位
                if slot_id not in [1, 2, 3]:
                    return format_error(INVALID_PARAMS, detail="slot_id必须是1、2或3")

                task = slots_manager.get_task(slot_id)
                if task:
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": f"槽位{slot_id}状态: {task.status.value}",
                        "data": task.to_dict()
                    }
                else:
                    return {
                        "success": True,
                        "error_code": None,
                        "user_message": f"槽位{slot_id}空闲",
                        "data": {"slot_id": slot_id, "status": "idle"}
                    }
            else:
                # 获取所有槽位
                all_tasks = slots_manager.get_all_slots_status()
                task_list = []
                for slot_id, task in all_tasks.items():
                    if task:
                        task_list.append(task.to_dict())
                    else:
                        task_list.append({"slot_id": slot_id, "status": "idle"})

                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"3槽位状态查询完成，共{len([t for t in task_list if t.get('status') != 'idle'])}个活跃任务",
                    "data": {"slots": task_list}
                }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取状态失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class CancelLongTask(BaseTool):
    """取消指定槽位的长期任务"""
    tool_id = "cancel_long_task"
    name = "取消长期任务"
    description = "取消指定槽位（1、2、3）中的长任务"
    input_schema = {
        "type": "object",
        "properties": {
            "slot_id": {
                "type": "integer",
                "enum": [1, 2, 3],
                "description": "槽位ID（1、2、3）"
            }
        },
        "required": ["slot_id"]
    }

    def _execute(self, **kwargs) -> dict:
        slot_id = kwargs.get("slot_id")

        if slot_id not in [1, 2, 3]:
            return format_error(INVALID_PARAMS, detail="slot_id必须是1、2或3")

        try:
            from core.task.long_task_slots import get_long_task_slots
            slots_manager = get_long_task_slots()

            task = slots_manager.get_task(slot_id)
            if not task:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"槽位{slot_id}没有任务")

            task_name = task.task_name
            success = slots_manager.stop_task(slot_id)

            if success:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"槽位{slot_id}的任务 '{task_name}' 已取消",
                    "data": {
                        "slot_id": slot_id,
                        "cancelled_task": task_name
                    }
                }
            else:
                return format_error(TOOL_EXECUTION_ERROR, detail="取消任务失败")

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"取消任务失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


# 导出列表
__all__ = [
    "CreateLongTask",
    "PauseLongTask",
    "ResumeLongTask",
    "GetLongTaskStatus",
    "CancelLongTask",
]
