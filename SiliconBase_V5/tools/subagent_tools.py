#!/usr/bin/env python3
"""
子代理管理工具 - 供 AI 调用子代理执行复杂任务

功能：
- 委派任务给子代理
- 查询子代理状态
- 干预子代理执行（暂停/恢复/取消）
- 获取可用子代理列表

作者: SiliconBase V5
日期: 2026-04-09
"""
import asyncio
from typing import Any

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error


class DelegateToSubAgent(BaseTool):
    """
    委派任务给子代理

    将复杂任务委派给专门的子代理执行。可用的子代理类型包括：
    - code_reviewer: 代码审查专家
    - tester: 测试工程师
    - researcher: 研究分析师
    - planner: 架构规划师
    - security_auditor: 安全审计员
    - performance_optimizer: 性能优化专家
    """
    tool_id = "delegate_to_subagent"
    name = "委派给子代理"
    description = (
        "将任务委派给专门的子代理执行。\\n"
        "可用类型: code_reviewer(代码审查)、tester(测试)、researcher(研究)、\\n"
        "planner(架构规划)、security_auditor(安全审计)、performance_optimizer(性能优化)"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "agent_type": {
                "type": "string",
                "enum": ["code_reviewer", "tester", "researcher", "planner", "security_auditor", "performance_optimizer"],
                "description": "子代理类型"
            },
            "task": {
                "type": "string",
                "description": "任务描述"
            },
            "context": {
                "type": "object",
                "description": "额外上下文信息（可选）"
            },
            "async_mode": {
                "type": "boolean",
                "description": "是否异步执行（默认false，同步等待结果）"
            }
        },
        "required": ["agent_type", "task"]
    }

    def _execute(self, **kwargs) -> dict:
        agent_type = kwargs.get("agent_type")
        task = kwargs.get("task")
        context = kwargs.get("context", {})
        async_mode = kwargs.get("async_mode", False)

        # 参数验证
        valid_types = ["code_reviewer", "tester", "researcher", "planner", "security_auditor", "performance_optimizer"]
        if agent_type not in valid_types:
            return format_error(
                INVALID_PARAMS,
                detail=f"agent_type必须是以下之一: {', '.join(valid_types)}"
            )

        if not task or not isinstance(task, str):
            return format_error(INVALID_PARAMS, detail="task必须是有效的字符串")

        try:
            from core.subagent import delegate

            # 调用子代理
            result = delegate(
                agent_type=agent_type,
                task=task,
                context=context,
                async_mode=async_mode
            )

            if async_mode:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": (
                        f"任务已委派给 {agent_type} 子代理（异步模式）\\n"
                        f"任务ID: {result.get('task_id', 'unknown')}\\n"
                        f"可通过子代理状态查询获取结果"
                    ),
                    "data": {
                        "agent_type": agent_type,
                        "task_id": result.get("task_id"),
                        "async": True,
                        "status": "running"
                    }
                }
            else:
                # 同步模式，直接返回结果
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"子代理 {agent_type} 执行完成",
                    "data": {
                        "agent_type": agent_type,
                        "result": result.get("result"),
                        "async": False,
                        "status": "completed"
                    }
                }

        except ImportError:
            return format_error(TOOL_EXECUTION_ERROR, detail="子代理模块未安装或不可用")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"委派任务失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class GetSubAgentStatus(BaseTool):
    """获取子代理状态"""
    tool_id = "get_subagent_status"
    name = "获取子代理状态"
    description = "查询子代理的运行时状态和进度"
    input_schema = {
        "type": "object",
        "properties": {
            "runtime_id": {
                "type": "string",
                "description": "子代理运行时ID（异步委派时返回）"
            }
        },
        "required": ["runtime_id"]
    }

    def _execute(self, **kwargs) -> dict:
        runtime_id = kwargs.get("runtime_id")

        if not runtime_id:
            return format_error(INVALID_PARAMS, detail="必须提供runtime_id")

        try:
            from core.subagent.manager import subagent_manager

            runtime = subagent_manager.get_runtime(runtime_id)
            if not runtime:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"子代理运行时未找到: {runtime_id}")

            return {
                "success": True,
                "error_code": None,
                "user_message": f"子代理状态: {runtime.status.value if hasattr(runtime.status, 'value') else runtime.status}",
                "data": {
                    "runtime_id": runtime_id,
                    "status": runtime.status.value if hasattr(runtime.status, 'value') else str(runtime.status),
                    "progress": getattr(runtime, 'progress', None),
                    "current_step": getattr(runtime, 'current_step', None)
                }
            }

        except ImportError:
            return format_error(TOOL_EXECUTION_ERROR, detail="子代理模块未安装或不可用")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取状态失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class InterveneSubAgent(BaseTool):
    """干预子代理执行"""
    tool_id = "intervene_subagent"
    name = "干预子代理"
    description = "对运行中的子代理进行干预：暂停、恢复、调整、重新规划或取消"
    input_schema = {
        "type": "object",
        "properties": {
            "runtime_id": {
                "type": "string",
                "description": "子代理运行时ID"
            },
            "action": {
                "type": "string",
                "enum": ["PAUSE", "RESUME", "ADJUST", "REPLAN", "CANCEL"],
                "description": "干预类型"
            },
            "reason": {
                "type": "string",
                "description": "干预原因"
            },
            "new_task": {
                "type": "string",
                "description": "新任务描述（REPLAN时使用）"
            },
            "adjustment": {
                "type": "string",
                "description": "调整建议（ADJUST时使用）"
            }
        },
        "required": ["runtime_id", "action"]
    }

    def _execute(self, **kwargs) -> dict:
        runtime_id = kwargs.get("runtime_id")
        action = kwargs.get("action")
        reason = kwargs.get("reason", "")
        new_task = kwargs.get("new_task", "")
        adjustment = kwargs.get("adjustment", "")

        if not runtime_id:
            return format_error(INVALID_PARAMS, detail="必须提供runtime_id")

        valid_actions = ["PAUSE", "RESUME", "ADJUST", "REPLAN", "CANCEL"]
        if action not in valid_actions:
            return format_error(INVALID_PARAMS, detail=f"action必须是以下之一: {', '.join(valid_actions)}")

        try:
            from core.subagent.manager import subagent_manager

            runtime = subagent_manager.get_runtime(runtime_id)
            if not runtime:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"子代理运行时未找到: {runtime_id}")

            # 执行干预
            if action == "PAUSE":
                success = runtime.pause(reason=reason)
                message = f"子代理已暂停: {reason}"
            elif action == "RESUME":
                success = runtime.resume()
                message = "子代理已恢复执行"
            elif action == "CANCEL":
                success = runtime.cancel(reason=reason)
                message = f"子代理已取消: {reason}"
            elif action == "REPLAN":
                if not new_task:
                    return format_error(INVALID_PARAMS, detail="REPLAN时必须提供new_task")
                success = runtime.replan(new_task=new_task)
                message = f"子代理已重新规划任务: {new_task}"
            elif action == "ADJUST":
                if not adjustment:
                    return format_error(INVALID_PARAMS, detail="ADJUST时必须提供adjustment")
                success = runtime.adjust(adjustment=adjustment)
                message = f"子代理已调整: {adjustment}"

            if success:
                return {
                    "success": True,
                    "error_code": None,
                    "user_message": message,
                    "data": {
                        "runtime_id": runtime_id,
                        "action": action,
                        "new_status": runtime.status.value if hasattr(runtime.status, 'value') else str(runtime.status)
                    }
                }
            else:
                return format_error(TOOL_EXECUTION_ERROR, detail=f"干预执行失败，当前状态可能不支持{action}")

        except ImportError:
            return format_error(TOOL_EXECUTION_ERROR, detail="子代理模块未安装或不可用")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"干预失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


class ListAvailableSubAgents(BaseTool):
    """获取可用子代理列表"""
    tool_id = "list_available_subagents"
    name = "列出可用子代理"
    description = "获取系统中所有可用的子代理类型及其能力描述"
    input_schema = {
        "type": "object",
        "properties": {}
    }

    def _execute(self, **kwargs) -> dict:
        try:
            from core.subagent.config import PRESET_SUBAGENTS

            agents = []
            for agent_type, config in PRESET_SUBAGENTS.items():
                agents.append({
                    "type": agent_type,
                    "name": config.get("name", agent_type),
                    "description": config.get("description", ""),
                    "capabilities": config.get("capabilities", [])
                })

            return {
                "success": True,
                "error_code": None,
                "user_message": f"系统中有 {len(agents)} 个可用子代理",
                "data": {
                    "agents": agents,
                    "count": len(agents)
                }
            }

        except ImportError:
            return format_error(TOOL_EXECUTION_ERROR, detail="子代理模块未安装或不可用")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"获取列表失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute, **kwargs)


# 导出列表
__all__ = [
    "DelegateToSubAgent",
    "GetSubAgentStatus",
    "InterveneSubAgent",
    "ListAvailableSubAgents",
]
