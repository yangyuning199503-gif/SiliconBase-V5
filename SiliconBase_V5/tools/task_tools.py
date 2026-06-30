#!/usr/bin/env python3
"""
任务管理工具 - 供 AI 创建、查询、修改、删除定时任务

增强功能：
- 支持多种触发类型：once(一次性)、interval(间隔)、cron(定时)
- 支持自然语言时间描述
- 支持执行指定工具
- 与 cloud_api 共用 TaskScheduler，确保任务能被正确执行

作者: SiliconBase V5
日期: 2026-04-09
"""
import asyncio
from datetime import datetime, timedelta
from typing import Any

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.task.task_scheduler import (
    ScheduledTask,
    ScheduledTaskStatus,
    TaskScheduler,
    get_task_scheduler,
)


class CreateTask(BaseTool):
    """
    创建定时任务工具

    支持三种触发方式：
    1. once: 一次性任务，用 execute_at 指定时间或 delay_seconds 延迟
    2. interval: 间隔任务，每隔一段时间执行
    3. cron: Cron表达式任务，按固定时间规则执行
    """
    tool_id = "create_task"
    name = "创建定时任务"
    description = (
        "创建一个定时任务，支持三种触发方式：\\n"
        "1. once: 一次性任务，用 delay_seconds 指定多少秒后执行，或用 execute_at 指定 ISO 格式时间\\n"
        "2. interval: 间隔任务，用 interval_seconds 指定间隔秒数\\n"
        "3. cron: Cron表达式，用 cron_expression 指定（如'0 8 * * *'表示每天8点）\\n"
        "任务可以执行指定工具，也可以只是提醒"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "任务名称（简短标识，如'每日备份'）"
            },
            "description": {
                "type": "string",
                "description": "任务描述，即要执行的指令或提醒内容"
            },
            "trigger_type": {
                "type": "string",
                "enum": ["once", "interval", "cron"],
                "description": "触发类型：once一次性、interval间隔、cron定时"
            },
            # once 类型配置
            "delay_seconds": {
                "type": "integer",
                "description": "多少秒后执行（用于 once 类型，优先级高于 execute_at）"
            },
            "execute_at": {
                "type": "string",
                "description": "ISO格式执行时间，如'2026-04-10T08:00:00'（once类型可选）"
            },
            # interval 类型配置
            "interval_seconds": {
                "type": "integer",
                "description": "间隔秒数（用于 interval 类型）"
            },
            # cron 类型配置
            "cron_expression": {
                "type": "string",
                "description": "Cron表达式（用于 cron 类型），如'0 8 * * *'表示每天8点"
            },
            # 通用配置
            "max_run_count": {
                "type": "integer",
                "description": "最大执行次数（可选，默认无限）"
            },
            "tool_to_execute": {
                "type": "string",
                "description": "要执行的工具ID（可选，默认不执行工具仅提醒）"
            },
            "tool_params": {
                "type": "object",
                "description": "工具执行参数（可选，当tool_to_execute指定时有效）"
            }
        },
        "required": ["name", "description", "trigger_type"]
    }

    def _execute(self, **kwargs) -> dict:
        """执行创建任务"""
        # 参数提取
        name = kwargs.get("name")
        description = kwargs.get("description")
        trigger_type = kwargs.get("trigger_type")

        # 触发配置参数
        delay_seconds = kwargs.get("delay_seconds")
        execute_at = kwargs.get("execute_at")
        interval_seconds = kwargs.get("interval_seconds")
        cron_expression = kwargs.get("cron_expression")
        max_run_count = kwargs.get("max_run_count")

        # 工具执行参数
        tool_to_execute = kwargs.get("tool_to_execute")
        tool_params = kwargs.get("tool_params", {})

        # 基本参数验证
        if not name or not isinstance(name, str):
            return format_error(INVALID_PARAMS, detail="name必须是有效的字符串")

        if not description or not isinstance(description, str):
            return format_error(INVALID_PARAMS, detail="description必须是有效的字符串")

        if trigger_type not in ["once", "interval", "cron"]:
            return format_error(
                INVALID_PARAMS,
                detail=f"trigger_type必须是'once'、'interval'或'cron'，当前为'{trigger_type}'"
            )

        # 获取调度器
        try:
            scheduler = get_task_scheduler()
        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"获取任务调度器失败: {str(e)}"
            )

        # 根据触发类型创建任务
        try:
            if trigger_type == "once":
                task = self._create_once_task(
                    scheduler, name, description, delay_seconds, execute_at,
                    max_run_count, tool_to_execute, tool_params
                )
            elif trigger_type == "interval":
                task = self._create_interval_task(
                    scheduler, name, description, interval_seconds,
                    max_run_count, tool_to_execute, tool_params
                )
            elif trigger_type == "cron":
                task = self._create_cron_task(
                    scheduler, name, description, cron_expression,
                    max_run_count, tool_to_execute, tool_params
                )

            if task is None:
                return format_error(TOOL_EXECUTION_ERROR, detail="创建任务失败")

            # 格式化返回信息
            trigger_desc = self._format_trigger_description(trigger_type, kwargs)

            return {
                "success": True,
                "error_code": None,
                "user_message": (
                    f"任务 '{name}' 创建成功！\\n"
                    f"任务ID: {task.task_id}\\n"
                    f"触发方式: {self._format_trigger_type(trigger_type)}\\n"
                    f"执行计划: {trigger_desc}"
                ),
                "data": {
                    "task_id": task.task_id,
                    "name": name,
                    "description": description,
                    "trigger_type": trigger_type,
                    "trigger_description": trigger_desc
                }
            }

        except ValueError as e:
            return format_error(INVALID_PARAMS, detail=str(e))
        except Exception as e:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail=f"创建任务失败: {str(e)}"
            )

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)

    def _create_once_task(
        self,
        scheduler: TaskScheduler,
        name: str,
        description: str,
        delay_seconds: int | None,
        execute_at: str | None,
        max_runs: int | None,
        tool_name: str | None,
        tool_params: dict
    ) -> ScheduledTask | None:
        """创建一次性任务"""
        # 确定执行时间
        if delay_seconds is not None:
            # 使用延迟秒数
            if delay_seconds <= 0:
                raise ValueError("delay_seconds必须大于0")
            execute_time = datetime.now() + timedelta(seconds=delay_seconds)
        elif execute_at:
            # 使用指定时间
            try:
                execute_time = datetime.fromisoformat(execute_at.replace('Z', '+00:00'))
            except ValueError as _exc:
                raise ValueError("execute_at格式错误，应为ISO格式如'2026-04-10T08:00:00'") from _exc
        else:
            # 默认5分钟后
            execute_time = datetime.now() + timedelta(minutes=5)

        # 创建任务
        return scheduler.create_once_task(
            name=name,
            description=description,
            scheduled_time=execute_time,
            tool_name=tool_name or "",
            tool_params=tool_params,
            max_runs=max_runs
        )

    def _create_interval_task(
        self,
        scheduler: TaskScheduler,
        name: str,
        description: str,
        interval_seconds: int | None,
        max_run_count: int | None,
        tool_name: str | None,
        tool_params: dict
    ) -> ScheduledTask | None:
        """创建间隔任务"""
        if interval_seconds is None or interval_seconds <= 0:
            raise ValueError("interval类型必须提供有效的 interval_seconds（大于0）")

        return scheduler.create_interval_task(
            name=name,
            description=description,
            interval_seconds=interval_seconds,
            tool_name=tool_name or "",
            tool_params=tool_params,
            max_run_count=max_run_count
        )

    def _create_cron_task(
        self,
        scheduler: TaskScheduler,
        name: str,
        description: str,
        cron_expression: str | None,
        max_run_count: int | None,
        tool_name: str | None,
        tool_params: dict
    ) -> ScheduledTask | None:
        """创建Cron任务"""
        if not cron_expression:
            raise ValueError("cron类型必须提供 cron_expression")

        # 简单验证Cron表达式格式
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError("cron_expression格式错误，应为5个字段（分 时 日 月 周），如'0 8 * * *'")

        return scheduler.create_cron_task(
            name=name,
            description=description,
            cron_expression=cron_expression,
            tool_name=tool_name or "",
            tool_params=tool_params,
            max_run_count=max_run_count
        )

    def _format_trigger_type(self, trigger_type: str) -> str:
        """格式化触发类型显示"""
        type_names = {
            "once": "一次性任务",
            "interval": "间隔任务",
            "cron": "定时任务(Cron)"
        }
        return type_names.get(trigger_type, trigger_type)

    def _format_trigger_description(self, trigger_type: str, kwargs: dict) -> str:
        """格式化触发描述"""
        if trigger_type == "once":
            delay = kwargs.get("delay_seconds")
            if delay:
                if delay < 60:
                    return f"{delay}秒后执行"
                elif delay < 3600:
                    return f"{delay//60}分钟后执行"
                else:
                    return f"{delay//3600}小时后执行"
            execute_at = kwargs.get("execute_at")
            if execute_at:
                return f"将于 {execute_at} 执行"
            return "5分钟后执行"

        elif trigger_type == "interval":
            seconds = kwargs.get("interval_seconds", 0)
            if seconds < 60:
                return f"每 {seconds} 秒执行一次"
            elif seconds < 3600:
                return f"每 {seconds//60} 分钟执行一次"
            elif seconds < 86400:
                return f"每 {seconds//3600} 小时执行一次"
            else:
                return f"每 {seconds//86400} 天执行一次"

        elif trigger_type == "cron":
            cron = kwargs.get("cron_expression", "")
            # 常用表达式简化显示
            if cron == "0 8 * * *":
                return "每天上午8点执行"
            elif cron == "0 0 * * *":
                return "每天午夜执行"
            elif cron == "0 */1 * * *":
                return "每小时执行"
            elif cron.startswith("*/"):
                minutes = cron.split()[0].replace("*/", "")
                return f"每 {minutes} 分钟执行"
            return f"按 Cron 规则执行: {cron}"

        return "未知"


class ListTasks(BaseTool):
    """列出所有定时任务"""
    tool_id = "list_tasks"
    name = "列出所有任务"
    description = "列出所有定时任务，可按状态筛选"
    input_schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "running", "completed", "failed", "paused"],
                "description": "按状态筛选（可选）"
            }
        }
    }

    def _execute(self, **kwargs) -> dict:
        status_str = kwargs.get("status")

        # 转换状态字符串为枚举
        status = None
        if status_str:
            try:
                status = ScheduledTaskStatus(status_str)
            except ValueError:
                return format_error(INVALID_PARAMS, detail=f"无效的状态: {status_str}")

        try:
            scheduler = get_task_scheduler()
            tasks = scheduler.list_tasks(status)

            # 格式化任务列表
            task_list = []
            for task in tasks:
                task_list.append({
                    "id": task.task_id,
                    "name": task.name,
                    "description": task.description if hasattr(task, 'description') else "",
                    "type": task.task_type.value if hasattr(task.task_type, 'value') else str(task.task_type),
                    "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                    "created_at": task.created_at if isinstance(task.created_at, str) else task.created_at.isoformat() if hasattr(task.created_at, 'isoformat') else str(task.created_at),
                    "next_run_at": task.next_run_at if hasattr(task, 'next_run_at') else None,
                    "run_count": task.run_count if hasattr(task, 'run_count') else 0
                })

            # 按创建时间倒序
            task_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"共找到 {len(task_list)} 个任务",
                "data": {"tasks": task_list, "total": len(task_list)}
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取任务列表失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class GetTask(BaseTool):
    """获取任务详情"""
    tool_id = "get_task"
    name = "获取任务详情"
    description = "根据任务ID获取单个任务的详细信息"
    input_schema = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "任务ID"
            }
        },
        "required": ["task_id"]
    }

    def _execute(self, **kwargs) -> dict:
        task_id = kwargs.get("task_id")
        if not task_id:
            return format_error(INVALID_PARAMS, detail="必须提供task_id")

        try:
            scheduler = get_task_scheduler()
            task = scheduler.get_task(task_id)

            if not task:
                return {
                    "success": False,
                    "error_code": "TASK_NOT_FOUND",
                    "user_message": f"任务 {task_id} 不存在",
                    "data": None
                }

            return {
                "success": True,
                "error_code": None,
                "user_message": f"获取任务 '{task.name}' 详情成功",
                "data": {
                    "id": task.task_id,
                    "name": task.name,
                    "description": task.description if hasattr(task, 'description') else "",
                    "type": task.task_type.value if hasattr(task.task_type, 'value') else str(task.task_type),
                    "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                    "created_at": task.created_at if isinstance(task.created_at, str) else task.created_at.isoformat() if hasattr(task.created_at, 'isoformat') else str(task.created_at),
                    "next_run_at": task.next_run_at if hasattr(task, 'next_run_at') else None,
                    "last_run_at": task.last_run_at if hasattr(task, 'last_run_at') else None,
                    "run_count": task.run_count if hasattr(task, 'run_count') else 0,
                    "tool_name": task.tool_name if hasattr(task, 'tool_name') else "",
                    "tool_params": task.tool_params if hasattr(task, 'tool_params') else {}
                }
            }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取任务详情失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class CancelTask(BaseTool):
    """取消/删除定时任务"""
    tool_id = "cancel_task"
    name = "取消任务"
    description = "根据任务ID取消或删除一个定时任务"
    input_schema = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "任务ID"
            }
        },
        "required": ["task_id"]
    }

    def _execute(self, **kwargs) -> dict:
        task_id = kwargs.get("task_id")
        if not task_id:
            return format_error(INVALID_PARAMS, detail="必须提供task_id")

        try:
            scheduler = get_task_scheduler()

            # 先检查任务是否存在
            task = scheduler.get_task(task_id)
            if not task:
                return {
                    "success": False,
                    "error_code": "TASK_NOT_FOUND",
                    "user_message": f"任务 {task_id} 不存在",
                    "data": None
                }

            # 取消任务
            success = scheduler.cancel_task(task_id)

            if success:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"任务 '{task.name}' 已取消",
                    "data": {"cancelled_id": task_id, "name": task.name}
                }
            else:
                return {
                    "success": False,
                    "error_code": "CANCEL_FAILED",
                    "user_message": f"任务 {task_id} 取消失败",
                    "data": None
                }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"取消任务失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


# 保持向后兼容的别名
DeleteTask = CancelTask

# 导出列表
__all__ = [
    "CreateTask",
    "ListTasks",
    "GetTask",
    "CancelTask",
    "DeleteTask",
]
