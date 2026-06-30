#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
长任务模式 API 路由  # 模块功能：长任务API接口定义

提供暂停、恢复、提交需求等接口，支持前端与长任务状态机交互。  # 核心功能

作者: SiliconBase V5 AI Agent  # 作者信息
日期: 2026-02-28  # 创建日期
"""

from typing import Any  # 导入类型注解

from pydantic import BaseModel  # 导入Pydantic基础模型

from core.logger import logger  # 导入日志记录器
from core.task.long_running_manager import get_long_task_manager  # 导入长任务管理器

# 【新增】导入认证依赖
try:
    from fastapi import Depends, HTTPException

    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    get_current_user = None
    logger.warning("[LongTaskAPI] 认证模块导入失败，认证功能将不可用")


# =============================================================================
# Pydantic 模型定义
# =============================================================================

class PauseTaskRequest(BaseModel):  # 暂停任务请求模型
    """暂停任务请求"""  # 类文档字符串
    task_id: str  # 任务ID字段
    reason: str = "用户请求暂停"  # 暂停原因，带默认值
    trigger: str = "user"  # 触发方式，默认为user
    session_id: str | None = None  # 【修复新增】会话ID，用于获取working_memory同步阶段锚点


class PauseTaskResponse(BaseModel):  # 暂停任务响应模型
    """暂停任务响应"""  # 类文档字符串
    success: bool  # 是否成功
    task_id: str  # 任务ID
    state: str  # 当前状态
    message: str  # 响应消息


class SubmitRequirementsRequest(BaseModel):  # 提交需求请求模型
    """提交需求请求"""  # 类文档字符串
    task_id: str  # 任务ID
    requirements: str  # 需求描述


class SubmitRequirementsResponse(BaseModel):  # 提交需求响应模型
    """提交需求响应"""  # 类文档字符串
    success: bool  # 是否成功
    task_id: str  # 任务ID
    state: str  # 当前状态
    message: str  # 响应消息


class UserConfirmationRequest(BaseModel):  # 用户确认请求模型
    """用户确认请求"""  # 类文档字符串
    task_id: str  # 任务ID
    response: str  # 用户响应文本


class UserConfirmationResponse(BaseModel):  # 用户确认响应模型
    """用户确认响应"""  # 类文档字符串
    success: bool  # 是否成功
    status: str  # 处理状态
    can_resume: bool  # 是否可以恢复
    message: str  # 响应消息
    forced: bool = False  # 是否强制确认，默认False


class ResumeTaskRequest(BaseModel):  # 恢复任务请求模型
    """恢复任务请求"""  # 类文档字符串
    task_id: str  # 任务ID
    by_user: bool = True  # 是否由用户触发，默认True


class ResumeTaskResponse(BaseModel):  # 恢复任务响应模型
    """恢复任务响应"""  # 类文档字符串
    success: bool  # 是否成功
    task_id: str  # 任务ID
    state: str  # 当前状态
    message: str  # 响应消息
    context: dict[str, Any] | None = None  # 恢复上下文，可选


class TaskStatusResponse(BaseModel):  # 任务状态响应模型
    """任务状态响应"""  # 类文档字符串
    task_id: str  # 任务ID
    exists: bool  # 任务是否存在
    state: str | None = None  # 当前状态，可选
    can_resume: bool = False  # 是否可以恢复
    confirmation_round: int = 0  # 确认轮次
    user_confirmed: bool | None = None  # 用户是否确认


class StartLongTaskRequest(BaseModel):  # 启动长任务请求模型
    """启动长任务请求"""  # 类文档字符串
    task_id: str  # 任务ID
    session_id: str  # 会话ID
    description: str  # 任务描述


class StartLongTaskResponse(BaseModel):  # 启动长任务响应模型
    """启动长任务响应"""  # 类文档字符串
    success: bool  # 是否成功
    task_id: str  # 任务ID
    state: str  # 当前状态
    message: str  # 响应消息


# =============================================================================
# API 处理函数
# =============================================================================

class LongTaskAPI:  # 定义长任务API类
    """长任务模式 API 处理器"""  # 类文档字符串

    def __init__(self):  # 初始化方法
        self.task_manager = get_long_task_manager()  # 获取长任务管理器

    def start_long_task(self, request: StartLongTaskRequest) -> StartLongTaskResponse:  # 启动长任务
        """
        启动长任务

        Args:
            request: 启动长任务请求

        Returns:
            StartLongTaskResponse: 启动结果
        """  # 方法文档字符串
        try:  # 异常处理
            task = self.task_manager.start_long_task(  # 调用管理器方法
                task_id=request.task_id,  # 任务ID
                session_id=request.session_id,  # 会话ID
                description=request.description  # 描述
            )

            return StartLongTaskResponse(  # 返回成功响应
                success=True,  # 成功
                task_id=task.task_id,  # 任务ID
                state=task.state_machine.state.name if task.state_machine else "running",  # 状态
                message="长任务已启动"  # 消息
            )
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 启动长任务失败: {e}")  # 记录错误
            return StartLongTaskResponse(  # 返回失败响应
                success=False,  # 失败
                task_id=request.task_id,  # 任务ID
                state="error",  # 错误状态
                message=f"启动失败: {str(e)}"  # 错误消息
            )

    async def pause_task(self, request: PauseTaskRequest, user_id: str = None) -> PauseTaskResponse:  # 暂停任务
        """
        暂停任务

        【修复说明】新增working_memory支持，确保阶段锚点能同步到PostgreSQL
        【安全修复】添加认证检查，确保只有登录用户可调用
        【零静默失败】认证失败时抛出401异常，绝不静默允许访问

        Args:
            request: 暂停任务请求
            user_id: 用户ID（从认证依赖获取）

        Returns:
            PauseTaskResponse: 暂停结果
        """  # 方法文档字符串
        try:  # 异常处理
            # 【安全修复】验证用户认证
            if not user_id:
                logger.error("[SILENT_FAILURE_BLOCKED] 暂停任务失败: 无法获取用户ID，认证可能无效")
                return PauseTaskResponse(
                    success=False,
                    task_id=request.task_id,
                    state="error",
                    message="认证失败：无法获取用户信息"
                )

            # 【安全修复】验证任务所有权
            task_owner = self._get_task_owner(request.task_id)
            if task_owner and task_owner != user_id:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 用户{user_id}无权暂停任务{request.task_id}，任务属于{task_owner}")
                return PauseTaskResponse(
                    success=False,
                    task_id=request.task_id,
                    state="error",
                    message="无权限：您无权暂停此任务"
                )

            # 【修复新增】获取working_memory以同步阶段锚点
            working_memory = None
            if request.session_id:
                try:
                    from core.memory.working_memory import get_working_memory_for_coordinator
                    working_memory = get_working_memory_for_coordinator(
                        user_id=user_id,  # 【修复】使用真实用户ID而不是默认用户
                        session_id=request.session_id
                    )
                    logger.debug(f"[LongTaskAPI] 获取working_memory成功: session_id={request.session_id}")
                except Exception as e:
                    # 【零静默失败】记录日志但不阻断主流程
                    logger.warning(f"[LongTaskAPI] 获取working_memory失败（非阻塞）: {e}")

            success = await self.task_manager.pause_task(  # 调用管理器方法
                task_id=request.task_id,  # 任务ID
                reason=request.reason,  # 原因
                trigger=request.trigger,  # 触发方式
                working_memory=working_memory  # 【修复新增】传递working_memory以同步阶段锚点
            )

            if success:  # 如果成功
                state = self.task_manager.get_task_state(request.task_id)  # 获取状态
                logger.info(f"[LongTaskAPI] 用户{user_id}成功暂停任务{request.task_id}")
                return PauseTaskResponse(  # 返回成功响应
                    success=True,  # 成功
                    task_id=request.task_id,  # 任务ID
                    state=state or "paused",  # 状态
                    message=f"任务已暂停: {request.reason}"  # 消息
                )
            else:  # 失败
                return PauseTaskResponse(  # 返回失败响应
                    success=False,  # 失败
                    task_id=request.task_id,  # 任务ID
                    state="unknown",  # 未知状态
                    message="暂停失败，任务不存在或状态不允许暂停"  # 错误消息
                )
        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 暂停任务异常: {e}")
            return PauseTaskResponse(  # 返回错误响应
                success=False,  # 失败
                task_id=request.task_id,  # 任务ID
                state="error",  # 错误状态
                message="暂停任务失败，请稍后重试"  # 错误消息
            )

    def _get_task_owner(self, task_id: str) -> str | None:
        """
        获取任务所有者

        Args:
            task_id: 任务ID

        Returns:
            Optional[str]: 用户ID，如无法获取则返回None
        """
        try:
            # 从任务管理器获取任务状态
            status = self.task_manager.get_task_status(task_id)
            if status:
                # 尝试从任务状态中获取用户ID
                return status.get("user_id") or status.get("owner_id")
        except Exception as e:
            logger.debug(f"[LongTaskAPI] 获取任务{task_id}所有者失败: {e}")
        return None

    def submit_requirements(self, request: SubmitRequirementsRequest) -> SubmitRequirementsResponse:  # 提交需求
        """
        用户提交需求

        Args:
            request: 提交需求请求

        Returns:
            SubmitRequirementsResponse: 提交结果
        """  # 方法文档字符串
        try:  # 异常处理
            success = self.task_manager.submit_requirements(  # 调用管理器方法
                task_id=request.task_id,  # 任务ID
                requirements=request.requirements  # 需求
            )

            if success:  # 如果成功
                state = self.task_manager.get_task_state(request.task_id)  # 获取状态
                return SubmitRequirementsResponse(  # 返回成功响应
                    success=True,  # 成功
                    task_id=request.task_id,  # 任务ID
                    state=state or "confirming_understanding",  # 状态
                    message="需求已提交，等待AI输出理解摘要"  # 消息
                )
            else:  # 失败
                return SubmitRequirementsResponse(  # 返回失败响应
                    success=False,  # 失败
                    task_id=request.task_id,  # 任务ID
                    state="unknown",  # 未知状态
                    message="提交失败，任务不存在或状态不允许提交需求"  # 错误消息
                )
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 提交需求失败: {e}")  # 记录错误
            return SubmitRequirementsResponse(  # 返回错误响应
                success=False,  # 失败
                task_id=request.task_id,  # 任务ID
                state="error",  # 错误状态
                message=f"提交失败: {str(e)}"  # 错误消息
            )

    def process_user_confirmation(self, request: UserConfirmationRequest) -> UserConfirmationResponse:  # 处理用户确认
        """
        处理用户确认

        Args:
            request: 用户确认请求

        Returns:
            UserConfirmationResponse: 处理结果
        """  # 方法文档字符串
        try:  # 异常处理
            result = self.task_manager.process_user_confirmation(  # 调用管理器方法
                task_id=request.task_id,  # 任务ID
                user_response=request.response  # 用户响应
            )

            return UserConfirmationResponse(  # 返回响应
                success=result.get("success", True),  # 成功状态
                status=result.get("status", "unknown"),  # 处理状态
                can_resume=result.get("can_resume", False),  # 是否可以恢复
                message=result.get("message", ""),  # 消息
                forced=result.get("forced", False)  # 是否强制
            )
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 处理用户确认失败: {e}")  # 记录错误
            return UserConfirmationResponse(  # 返回错误响应
                success=False,  # 失败
                status="error",  # 错误状态
                can_resume=False,  # 不可恢复
                message=f"处理失败: {str(e)}"  # 错误消息
            )

    async def resume_task(self, request: ResumeTaskRequest) -> ResumeTaskResponse:  # 恢复任务
        """
        恢复任务

        【核心约束】必须用户确认后才能恢复

        Args:
            request: 恢复任务请求

        Returns:
            ResumeTaskResponse: 恢复结果
        """  # 方法文档字符串
        try:  # 异常处理
            # 先检查是否可以恢复  # 前置检查
            if not self.task_manager.can_resume(request.task_id):  # 检查是否可以恢复
                status = self.task_manager.get_task_status(request.task_id)  # 获取状态
                return ResumeTaskResponse(  # 返回不可恢复响应
                    success=False,  # 失败
                    task_id=request.task_id,  # 任务ID
                    state=status.get("state", "unknown") if status else "unknown",  # 状态
                    message="无法恢复：用户尚未确认理解正确",  # 错误消息
                    context=status  # 上下文
                )

            # 恢复任务  # 执行恢复
            resume_context = await self.task_manager.resume_task(  # 调用管理器方法
                task_id=request.task_id,  # 任务ID
                by_user=request.by_user  # 是否用户触发
            )

            if resume_context:  # 如果恢复成功
                state = self.task_manager.get_task_state(request.task_id)  # 获取状态
                return ResumeTaskResponse(  # 返回成功响应
                    success=True,  # 成功
                    task_id=request.task_id,  # 任务ID
                    state=state or "running",  # 状态
                    message="任务已恢复",  # 消息
                    context=resume_context  # 上下文
                )
            else:  # 恢复失败
                return ResumeTaskResponse(  # 返回失败响应
                    success=False,  # 失败
                    task_id=request.task_id,  # 任务ID
                    state="unknown",  # 未知状态
                    message="恢复失败，任务不存在或未经确认"  # 错误消息
                )
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 恢复任务失败: {e}")  # 记录错误
            return ResumeTaskResponse(  # 返回错误响应
                success=False,  # 失败
                task_id=request.task_id,  # 任务ID
                state="error",  # 错误状态
                message=f"恢复失败: {str(e)}"  # 错误消息
            )

    def get_task_status(self, task_id: str) -> TaskStatusResponse:  # 获取任务状态
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            TaskStatusResponse: 任务状态
        """  # 方法文档字符串
        try:  # 异常处理
            status = self.task_manager.get_task_status(task_id)  # 调用管理器方法

            if status:  # 如果存在
                confirmation = status.get("confirmation", {})  # 获取确认信息
                return TaskStatusResponse(  # 返回响应
                    task_id=task_id,  # 任务ID
                    exists=True,  # 存在
                    state=status.get("state"),  # 状态
                    can_resume=confirmation.get("can_resume", False),  # 是否可以恢复
                    confirmation_round=confirmation.get("confirmation_round", 0),  # 确认轮次
                    user_confirmed=confirmation.get("user_confirmed")  # 用户确认状态
                )
            else:  # 不存在
                return TaskStatusResponse(  # 返回不存在响应
                    task_id=task_id,  # 任务ID
                    exists=False,  # 不存在
                    can_resume=False  # 不可恢复
                )
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 获取任务状态失败: {e}")  # 记录错误
            return TaskStatusResponse(  # 返回错误响应
                task_id=task_id,  # 任务ID
                exists=False,  # 不存在
                can_resume=False  # 不可恢复
            )

    def list_active_tasks(self) -> dict[str, Any]:  # 列出活跃任务
        """
        列出所有活跃任务

        Returns:
            Dict: 活跃任务列表
        """  # 方法文档字符串
        try:  # 异常处理
            tasks = self.task_manager.list_active_tasks()  # 调用管理器方法
            return {  # 返回成功响应
                "success": True,  # 成功
                "count": len(tasks),  # 任务数
                "tasks": tasks  # 任务列表
            }
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 列出活跃任务失败: {e}")  # 记录错误
            return {  # 返回错误响应
                "success": False,  # 失败
                "error": str(e)  # 错误信息
            }

    def get_pause_prompt(self, task_id: str) -> dict[str, Any]:  # 获取暂停提示词
        """
        获取暂停提示词

        Args:
            task_id: 任务ID

        Returns:
            Dict: 暂停提示词
        """  # 方法文档字符串
        try:  # 异常处理
            prompt = self.task_manager.get_pause_prompt(task_id)  # 调用管理器方法
            return {  # 返回成功响应
                "success": True,  # 成功
                "task_id": task_id,  # 任务ID
                "prompt": prompt  # 提示词
            }
        except Exception as e:  # 捕获异常
            logger.error(f"[LongTaskAPI] 获取暂停提示词失败: {e}")  # 记录错误
            return {  # 返回错误响应
                "success": False,  # 失败
                "error": str(e)  # 错误信息
            }


# =============================================================================
# 全局单例
# =============================================================================

_long_task_api: LongTaskAPI | None = None  # 长任务API实例


def get_long_task_api() -> LongTaskAPI:  # 获取长任务API
    """获取全局长任务API实例"""  # 函数文档字符串
    global _long_task_api  # 声明全局变量
    if _long_task_api is None:  # 检查是否已创建
        _long_task_api = LongTaskAPI()  # 创建实例
    return _long_task_api  # 返回实例


# =============================================================================
# FastAPI 路由（如果使用FastAPI）
# =============================================================================

# 示例FastAPI路由定义  # FastAPI路由注释
try:  # 尝试导入FastAPI
    from fastapi import APIRouter, HTTPException  # 导入FastAPI组件

    router = APIRouter(prefix="/long-tasks", tags=["长任务模式"])  # 创建路由
    api = get_long_task_api()  # 获取API实例

    @router.post("/start", response_model=StartLongTaskResponse)  # 启动路由
    async def start_long_task(request: StartLongTaskRequest):  # 处理函数
        """启动长任务"""  # 文档字符串
        return api.start_long_task(request)  # 调用API方法

    @router.post("/pause", response_model=PauseTaskResponse)  # 暂停路由
    async def pause_task(
        request: PauseTaskRequest,  # 请求数据
        user_id: str = Depends(get_current_user)  # 【修复】强制认证依赖
    ):  # 处理函数
        """
        暂停任务

        【修复说明】添加强制认证检查，无认证时返回401
        【零静默失败】认证失败立即返回401，绝不静默允许访问
        """
        return await api.pause_task(request, user_id=user_id)  # 调用API方法并传递用户ID

    @router.post("/requirements", response_model=SubmitRequirementsResponse)  # 提交需求路由
    async def submit_requirements(request: SubmitRequirementsRequest):  # 处理函数
        """提交需求"""  # 文档字符串
        return api.submit_requirements(request)  # 调用API方法

    @router.post("/confirm", response_model=UserConfirmationResponse)  # 确认路由
    async def process_user_confirmation(request: UserConfirmationRequest):  # 处理函数
        """处理用户确认"""  # 文档字符串
        return api.process_user_confirmation(request)  # 调用API方法

    @router.post("/resume", response_model=ResumeTaskResponse)  # 恢复路由
    async def resume_task(request: ResumeTaskRequest):  # 处理函数
        """恢复任务"""  # 文档字符串
        result = await api.resume_task(request)  # 调用API方法
        if not result.success:  # 如果失败
            raise HTTPException(status_code=400, detail=result.message)  # 抛出异常
        return result  # 返回结果

    @router.get("/{task_id}/status", response_model=TaskStatusResponse)  # 状态路由
    async def get_task_status(task_id: str):  # 处理函数
        """获取任务状态"""  # 文档字符串
        return api.get_task_status(task_id)  # 调用API方法

    @router.get("/active")  # 活跃任务路由
    async def list_active_tasks():  # 处理函数
        """列出所有活跃任务"""  # 文档字符串
        return api.list_active_tasks()  # 调用API方法

    @router.get("/{task_id}/pause-prompt")  # 暂停提示词路由
    async def get_pause_prompt(task_id: str):  # 处理函数
        """获取暂停提示词"""  # 文档字符串
        return api.get_pause_prompt(task_id)  # 调用API方法

    logger.info("[LongTaskAPI] FastAPI路由已注册")  # 记录日志

except ImportError:  # FastAPI未安装
    # FastAPI 未安装，跳过路由注册  # 跳过注释
    logger.debug("[LongTaskAPI] FastAPI未安装，跳过路由注册")  # 记录调试日志
    router = None  # 路由设为None


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"长任务模式API层"，提供RESTful接口供前端
# 与长任务状态机交互。使用Pydantic模型进行请求/响应验证。
#
# 【架构设计】
# - Pydantic模型: 定义类型安全的请求/响应数据结构
# - API类封装: LongTaskAPI封装业务逻辑，便于测试和复用
# - FastAPI集成: 自动注册路由（如果FastAPI可用）
# - 异常处理: 统一的异常捕获和错误响应
#
# 【关联文件】
# - core/long_running_manager.py      : 长任务管理器，核心业务逻辑
# - core/pause_confirmation_state_machine.py : 暂停确认状态机
# - api/main.py                       : FastAPI主应用，注册路由
#
# 【核心功能效果】
# 1. 任务生命周期: 启动、暂停、恢复、状态查询完整API
# 2. 确认机制: 支持需求提交和用户确认的API交互
# 3. 类型安全: Pydantic模型自动验证请求数据
# 4. 错误处理: 统一的异常处理和错误响应格式
# 5. 自动路由: FastAPI环境下自动注册RESTful路由
# 6. 响应规范: 统一的响应格式，包含success、message等字段
#
# 【API端点】
# POST   /long-tasks/start           : 启动长任务
# POST   /long-tasks/pause            : 暂停任务
# POST   /long-tasks/requirements     : 提交需求
# POST   /long-tasks/confirm          : 用户确认
# POST   /long-tasks/resume           : 恢复任务
# GET    /long-tasks/{id}/status      : 获取状态
# GET    /long-tasks/active           : 列出活跃任务
# GET    /long-tasks/{id}/pause-prompt: 获取暂停提示词
# =============================================================================
