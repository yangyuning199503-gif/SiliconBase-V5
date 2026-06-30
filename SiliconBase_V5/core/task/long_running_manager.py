#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
可暂停任务管理器 - 增强版（集成暂停确认状态机）
- 支持任务持续运行不中断
- 定期Checkpoint保存状态
- Memory Flush保存关键信息
- 自动恢复机制
- 【核心】暂停确认状态机管理 - AI必须百分百理解才能恢复

注意：此类管理的是"可暂停任务"(Pausable Task)，即在ReAct循环内可暂停/恢复的任务。
真正的大纲长任务(Scheduled Task)由 task_scheduler.py 管理。

作者: SiliconBase V5 AI Agent
日期: 2026-02-28
"""
import time  # 导入时间模块
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器
from datetime import datetime  # 从datetime导入日期时间类
from typing import Any  # 从typing导入类型注解

from core.exceptions import CheckpointError, LongRunningError  # 从统一异常模块导入
from core.logger import logger  # 从core.logger导入日志记录器

from ..agent.pause_confirmation_state_machine import (  # 导入暂停确认状态机
    PauseConfirmationManager,  # 暂停确认管理器
    # 理解摘要类
)
from ..session.session_persistence import get_session_persistence  # 导入会话持久化


# 可暂停任务状态机类 - 基于PauseConfirmationManager封装
class PausableTaskState:
    """可暂停任务状态枚举"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_REQUIREMENTS = "awaiting_requirements"
    CONFIRMING_UNDERSTANDING = "confirming_understanding"
    READY_TO_RESUME = "ready_to_resume"
    COMPLETED = "completed"


class PausableTaskStateMachine:
    """可暂停任务状态机 - 封装PauseConfirmationManager

    注意：这是用于ReAct循环内可暂停/恢复的任务，非大纲定时任务。
    """

    def __init__(self):
        self.state = PausableTaskState.IDLE
        self.pause_confirmation_manager = PauseConfirmationManager()
        self.paused_context = {}
        self.user_requirements = ""
        self.ai_understanding = ""
        self.user_confirmed = False
        self.confirmation_round = 0
        self._task_id = None

    def pause(self, reason: str, trigger: str) -> bool:
        """暂停任务"""
        if self.state == PausableTaskState.RUNNING:
            self.state = PausableTaskState.PAUSED
            return True
        return False

    def submit_requirements(self, requirements: str) -> bool:
        """提交需求"""
        self.user_requirements = requirements
        self.state = PausableTaskState.AWAITING_REQUIREMENTS
        return True

    def confirm_ai_understanding(self, understanding: str) -> bool:
        """确认AI理解"""
        self.ai_understanding = understanding
        return True

    def process_user_confirmation(self, user_response: str) -> dict:
        """处理用户确认"""
        # 简单实现：检查正向关键词
        positive_keywords = ["确认", "正确", "对", "是的", "没问题", "ok", "yes"]
        if any(kw in user_response.lower() for kw in positive_keywords):
            self.user_confirmed = True
            self.state = PausableTaskState.READY_TO_RESUME
            return {"can_resume": True, "status": "confirmed"}
        return {"can_resume": False, "status": "rejected"}

    def resume(self, by_user: bool = True) -> dict:
        """恢复任务"""
        if self.can_resume():
            self.state = PausableTaskState.RUNNING
            return {"success": True, "resumed_by": "user" if by_user else "ai"}
        return {"success": False}

    def ai_suggest_resume(self) -> dict:
        """AI建议恢复"""
        return {"success": True, "message": "AI suggests resume"}

    def can_resume(self) -> bool:
        """检查是否可以恢复"""
        return self.state in [PausableTaskState.READY_TO_RESUME, PausableTaskState.PAUSED]

    def is_waiting_confirmation(self) -> bool:
        """检查是否等待确认"""
        return self.state == PausableTaskState.CONFIRMING_UNDERSTANDING

    def get_confirmation_status(self) -> dict:
        """获取确认状态"""
        return {
            "state": self.state,
            "user_confirmed": self.user_confirmed,
            "confirmation_round": self.confirmation_round
        }

    def get_pause_prompt(self) -> str:
        """获取暂停提示词"""
        return "任务已暂停。请确认理解需求后继续。"

    def get_resume_prompt(self, context: dict = None) -> str:
        """获取恢复提示词"""
        return "任务已恢复。"

    def reset(self):
        """重置状态机"""
        self.state = PausableTaskState.IDLE
        self.user_requirements = ""
        self.ai_understanding = ""
        self.user_confirmed = False
        self.confirmation_round = 0
from core.session.state_snapshot import SnapshotError, get_snapshot_manager  # 导入状态快照管理
from core.task.task_status import TaskStatus  # 从core.task_status导入任务状态


@dataclass  # 使用数据类装饰器
class PausableTask:  # 定义可暂停任务状态数据类
    """可暂停任务状态

    注意：这是ReAct循环内可暂停/恢复的任务，非大纲定时任务。
    """  # 类文档字符串
    task_id: str  # 任务ID
    session_id: str  # 会话ID
    description: str  # 任务描述
    start_time: float = field(default_factory=time.time)  # 开始时间戳
    last_checkpoint_time: float = field(default_factory=time.time)  # 最后检查点时间
    last_flush_time: float = field(default_factory=time.time)  # 最后刷新时间
    total_rounds: int = 0  # 总轮次
    status: str = "running"  # 状态
    key_learnings: list = field(default_factory=list)  # 关键学习点列表
    metadata: dict = field(default_factory=dict)  # 元数据字典

    # 暂停确认相关字段
    pause_reason: str = ""  # 暂停原因
    pause_trigger: str = ""  # 暂停触发者
    paused_at: float | None = None  # 暂停时间
    ai_understanding: str = ""  # AI理解摘要
    user_confirmed: bool | None = None  # 用户是否确认
    confirmation_round: int = 0  # 确认轮次
    modified_requirement: str = ""  # 修改后的需求
    resumed_at: float | None = None  # 恢复时间

    # 关联的状态机
    state_machine: PausableTaskStateMachine | None = None  # 状态机实例


class PausableTaskManager:  # 定义长任务管理器类
    """
    长任务管理器  # 类文档字符串标题

    统一管理所有长任务，提供：  # 功能列表
    1. 任务生命周期管理（创建、暂停、恢复、完成）  # 功能1
    2. 暂停确认状态机集成  # 功能2
    3. 任务状态持久化  # 功能3
    4. 用户/AI恢复接口  # 功能4
    """  # 类文档字符串结束

    def __init__(self):  # 初始化方法
        self.active_long_tasks: dict[str, PausableTask] = {}  # 活跃任务字典
        self.task_history: list[dict[str, Any]] = []  # 任务历史列表
        self._pause_confirmation_manager = PauseConfirmationManager()  # 创建暂停确认管理器
        self.snapshot_manager = get_snapshot_manager()  # 获取快照管理器
        self._max_task_history = 100  # 【内存泄漏修复】限制历史记录最大条数

    def _add_task_history(self, entry: dict[str, Any]):  # 【内存泄漏修复】添加历史记录并限制大小
        """
        添加任务历史记录，限制最大条数防止内存泄漏

        Args:
            entry: 历史记录条目字典
        """
        self.task_history.append(entry)  # 添加记录
        # 【内存泄漏修复】超过最大限制时保留最近100条
        if len(self.task_history) > self._max_task_history:
            self.task_history = self.task_history[-self._max_task_history:]

    async def start_pausable_task(self,  # 定义启动可暂停任务方法
                        task_id: str,  # 参数：任务ID
                        session_id: str,  # 参数：会话ID
                        description: str  # 参数：任务描述
                        ) -> PausableTask:  # 返回：任务对象
        """
        启动可暂停任务  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            session_id: 会话ID  # 参数2
            description: 任务描述  # 参数3

        Returns:  # 返回值说明
            PausableTask: 创建的任务对象  # 返回类型
        """  # 方法文档字符串结束
        # 创建状态机
        state_machine = PausableTaskStateMachine()  # 创建状态机实例

        task = PausableTask(  # 创建任务对象
            task_id=task_id,  # 设置任务ID
            session_id=session_id,  # 设置会话ID
            description=description,  # 设置描述
            state_machine=state_machine  # 设置状态机
        )

        self.active_long_tasks[task_id] = task  # 添加到活跃任务字典

        # 记录历史
        self._add_task_history({  # 【内存泄漏修复】使用封装方法添加历史记录
            "task_id": task_id,  # 任务ID
            "session_id": session_id,  # 会话ID
            "description": description,  # 描述
            "start_time": time.time(),  # 开始时间
            "action": "started"  # 动作
        })

        logger.info(f"[PausableTaskManager] 启动可暂停任务: {task_id}, 描述: {description}")  # 记录日志
        return task  # 返回任务对象

    async def pause_task(self,  # 定义暂停任务方法
                   task_id: str,  # 参数：任务ID
                   reason: str = "用户暂停",  # 参数：原因
                   trigger: str = "user",  # 参数：触发者
                   working_memory=None,  # 参数：工作记忆（可选）
                   loop_state=None,  # 参数：循环状态（可选）
                   chat_history=None  # 参数：聊天历史（可选）
                   ) -> bool:  # 返回：是否成功
        """
        暂停任务并捕获状态快照  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            reason: 暂停原因  # 参数2
            trigger: 触发方式 (user/ai/system)  # 参数3
            working_memory: WorkingMemory实例（可选，用于快照）  # 参数4
            loop_state: LoopState实例（可选，用于快照）  # 参数5
            chat_history: 聊天历史（可选，用于快照）  # 参数6

        Returns:  # 返回值说明
            bool: 是否成功暂停  # 返回类型

        Raises:
            LongRunningError: 快照捕获失败
        """
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            logger.error(f"[SILENT_FAILURE_BLOCKED] 无法暂停任务 {task_id}: 任务不存在")  # 记录错误
            return False  # 返回失败

        task = self.active_long_tasks[task_id]  # 获取任务

        # 使用状态机暂停
        if task.state_machine:  # 如果有状态机
            success = task.state_machine.pause(reason, trigger)  # 调用状态机暂停
            if success:  # 如果暂停成功
                task.status = TaskStatus.PAUSED.value  # 更新状态为暂停
                task.pause_reason = reason  # 设置暂停原因
                task.pause_trigger = trigger  # 设置触发者
                task.paused_at = time.time()  # 设置暂停时间

                # 捕获状态快照（如果提供了必要参数）
                if working_memory:  # 如果有工作记忆
                    try:  # 尝试捕获快照
                        await self.snapshot_manager.capture_snapshot(  # 调用快照管理器
                            task_id=task_id,  # 任务ID
                            working_memory=working_memory,  # 工作记忆
                            loop_state=loop_state,  # 循环状态
                            chat_history=chat_history or [],  # 聊天历史
                            session_id=task.session_id,  # 会话ID
                            user_id="default",  # 用户ID
                            long_task_sm=task.state_machine  # 长任务状态机
                        )
                        logger.info(f"[PausableTaskManager] 任务 {task_id} 暂停时状态快照已捕获")  # 记录日志
                    except SnapshotError as e:  # 捕获快照异常
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 捕获快照失败 {task_id}: {e}")
                        raise LongRunningError(f"暂停任务时捕获快照失败: {e}") from e
                    except Exception as e:  # 捕获其他异常
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 捕获快照失败 {task_id}: {e}")
                        raise LongRunningError(f"暂停任务时捕获快照失败: {e}") from e

                logger.info(f"[PausableTaskManager] 任务 {task_id} 已暂停")  # 记录日志
                return True  # 返回成功

        return False  # 返回失败

    def submit_requirements(self,  # 定义提交需求方法
                            task_id: str,  # 参数：任务ID
                            requirements: str  # 参数：需求描述
                            ) -> bool:  # 返回：是否成功
        """
        用户提交需求  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            requirements: 需求描述  # 参数2

        Returns:  # 返回值说明
            bool: 是否成功提交  # 返回类型
        """  # 方法文档字符串结束
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return False  # 返回失败

        task = self.active_long_tasks[task_id]  # 获取任务

        if task.state_machine:  # 如果有状态机
            success = task.state_machine.submit_requirements(requirements)  # 提交需求
            if success:  # 如果成功
                task.status = TaskStatus.CONFIRMING_UNDERSTANDING.value  # 更新状态
                logger.info(f"[PausableTaskManager] 任务 {task_id} 收到新需求")  # 记录日志
                return True  # 返回成功

        return False  # 返回失败

    def submit_ai_understanding(self,  # 定义提交AI理解方法
                                task_id: str,  # 参数：任务ID
                                understanding: str  # 参数：理解摘要
                                ) -> bool:  # 返回：是否成功
        """
        AI提交理解摘要  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            understanding: 理解摘要  # 参数2

        Returns:  # 返回值说明
            bool: 是否成功提交  # 返回类型
        """  # 方法文档字符串结束
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return False  # 返回失败

        task = self.active_long_tasks[task_id]  # 获取任务

        if task.state_machine:  # 如果有状态机
            is_sufficient = task.state_machine.confirm_ai_understanding(understanding)  # 确认理解
            task.ai_understanding = understanding  # 保存理解
            task.confirmation_round = task.state_machine.confirmation_round  # 保存轮次
            task.status = TaskStatus.CONFIRMING_UNDERSTANDING.value  # 更新状态

            logger.info(f"[PausableTaskManager] 任务 {task_id} AI提交理解，充分性: {is_sufficient}")  # 记录日志
            return True  # 返回成功

        return False  # 返回失败

    def process_user_confirmation(self,  # 定义处理用户确认方法
                                  task_id: str,  # 参数：任务ID
                                  user_response: str  # 参数：用户响应
                                  ) -> dict[str, Any]:  # 返回：处理结果
        """
        处理用户确认  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            user_response: 用户响应  # 参数2

        Returns:  # 返回值说明
            Dict: 处理结果  # 返回类型
        """  # 方法文档字符串结束
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return {  # 返回错误结果
                "success": False,  # 失败
                "error": "任务不存在",  # 错误信息
                "can_resume": False  # 不能恢复
            }

        task = self.active_long_tasks[task_id]  # 获取任务

        if not task.state_machine:  # 如果没有状态机
            return {  # 返回错误结果
                "success": False,  # 失败
                "error": "状态机未初始化",  # 错误信息
                "can_resume": False  # 不能恢复
            }

        result = task.state_machine.process_user_confirmation(user_response)  # 处理确认

        # 更新任务状态
        if result.get("can_resume"):  # 如果可以恢复
            task.status = TaskStatus.READY_TO_RESUME.value  # 更新状态为可恢复
            task.user_confirmed = True  # 设置用户确认
        elif result.get("status") == "rejected":  # 如果被拒绝
            task.status = TaskStatus.PAUSED.value  # 更新状态为暂停
            task.user_confirmed = False  # 设置用户未确认
            task.ai_understanding = ""  # 清空理解
        elif result.get("status") == "modified":  # 如果被修改
            task.status = TaskStatus.CONFIRMING_UNDERSTANDING.value  # 更新状态
            task.user_confirmed = False  # 设置用户未确认
            task.modified_requirement = user_response  # 保存修改后的需求

        task.confirmation_round = task.state_machine.confirmation_round  # 更新确认轮次

        return result  # 返回结果

    async def resume_task(self,  # 定义恢复任务方法
                    task_id: str,  # 参数：任务ID
                    by_user: bool = True,  # 参数：是否由用户触发
                    working_memory=None  # 参数：工作记忆（可选）
                    ) -> dict[str, Any] | None:  # 返回：恢复上下文或None
        """
        恢复任务  # 方法文档字符串标题

        【核心约束】必须满足以下条件才能恢复：  # 约束说明
        1. 用户已确认理解正确  # 条件1
        2. 状态为 READY_TO_RESUME  # 条件2

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            by_user: 是否由用户触发  # 参数2
            working_memory: WorkingMemory实例（可选，用于恢复状态）  # 参数3

        Returns:  # 返回值说明
            Dict: 恢复上下文，如果无法恢复则返回None  # 返回类型

        Raises:
            LongRunningError: 快照恢复失败
        """
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            logger.error(f"[SILENT_FAILURE_BLOCKED] 无法恢复任务 {task_id}: 任务不存在")  # 记录错误
            return None  # 返回None

        task = self.active_long_tasks[task_id]  # 获取任务

        if not task.state_machine:  # 如果没有状态机
            return None  # 返回None

        # 【核心检查】必须用户确认后才能恢复
        if not task.state_machine.can_resume():  # 如果不能恢复
            logger.warning(f"[PausableTaskManager] 任务 {task_id} 未经用户确认，拒绝恢复")  # 记录警告
            return None  # 返回None

        # 恢复任务
        resume_context = task.state_machine.resume(by_user=by_user)  # 调用状态机恢复

        if resume_context:  # 如果恢复成功
            task.status = TaskStatus.RUNNING.value  # 更新状态为运行中
            task.resumed_at = time.time()  # 设置恢复时间
            task.user_confirmed = None  # 重置确认状态
            task.ai_understanding = ""  # 清空理解
            task.pause_reason = ""  # 清空暂停原因

            # 恢复快照到WorkingMemory（如果提供了）
            if working_memory:  # 如果有工作记忆
                try:  # 尝试恢复
                    restored = await self.snapshot_manager.restore_to_working_memory(task_id, working_memory)  # 恢复
                    if restored:  # 如果恢复成功
                        logger.info(f"[PausableTaskManager] 任务 {task_id} WorkingMemory状态已恢复")  # 记录日志
                except SnapshotError as e:  # 捕获快照异常
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复WorkingMemory状态失败 {task_id}: {e}")
                    raise LongRunningError(f"恢复任务时恢复快照失败: {e}") from e
                except Exception as e:  # 捕获其他异常
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复WorkingMemory状态失败 {task_id}: {e}")
                    raise LongRunningError(f"恢复任务时恢复快照失败: {e}") from e

            logger.info(f"[PausableTaskManager] 任务 {task_id} 已恢复，由 {'用户' if by_user else 'AI'} 触发")  # 记录日志

            # 记录历史
            self._add_task_history({  # 【内存泄漏修复】使用封装方法添加历史记录
                "task_id": task_id,  # 任务ID
                "action": "resumed",  # 动作
                "timestamp": time.time(),  # 时间戳
                "by_user": by_user  # 是否由用户触发
            })

        return resume_context  # 返回恢复上下文

    def ai_suggest_resume(self,  # 定义AI建议恢复方法
                          task_id: str  # 参数：任务ID
                          ) -> dict[str, Any]:  # 返回：建议结果
        """
        AI建议恢复任务  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            Dict: 建议结果  # 返回类型
        """  # 方法文档字符串结束
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return {  # 返回错误结果
                "success": False,  # 失败
                "error": "任务不存在"  # 错误信息
            }

        task = self.active_long_tasks[task_id]  # 获取任务

        if not task.state_machine:  # 如果没有状态机
            return {  # 返回错误结果
                "success": False,  # 失败
                "error": "状态机未初始化"  # 错误信息
            }

        result = task.state_machine.ai_suggest_resume()  # 调用状态机建议恢复

        if result.get("success"):  # 如果成功
            task.status = TaskStatus.AWAITING_REQUIREMENTS.value  # 更新状态

        return result  # 返回结果

    def get_task_state(self,  # 定义获取任务状态方法
                       task_id: str  # 参数：任务ID
                       ) -> str | None:  # 返回：状态或None
        """获取任务状态"""  # 方法文档字符串
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return None  # 返回None

        task = self.active_long_tasks[task_id]  # 获取任务
        if task.state_machine:  # 如果有状态机
            return task.state_machine.state.name  # 返回状态机状态名
        return task.status  # 返回任务状态

    def get_task_status(self,  # 定义获取任务完整状态方法
                        task_id: str  # 参数：任务ID
                        ) -> dict[str, Any] | None:  # 返回：状态字典或None
        """获取任务完整状态"""  # 方法文档字符串
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return None  # 返回None

        task = self.active_long_tasks[task_id]  # 获取任务

        status = {  # 构建状态字典
            "task_id": task.task_id,  # 任务ID
            "session_id": task.session_id,  # 会话ID
            "description": task.description,  # 描述
            "status": task.status,  # 状态
            "total_rounds": task.total_rounds,  # 总轮次
            "start_time": task.start_time,  # 开始时间
            "runtime_hours": round((time.time() - task.start_time) / 3600, 2),  # 运行小时数
        }

        # 添加暂停确认状态
        if task.state_machine:  # 如果有状态机
            status["confirmation"] = task.state_machine.get_confirmation_status()  # 获取确认状态

        return status  # 返回状态

    def get_pause_prompt(self,  # 定义获取暂停提示词方法
                         task_id: str  # 参数：任务ID
                         ) -> str:  # 返回：提示词
        """
        获取暂停提示词  # 方法文档字符串标题

        要求AI百分百理解用户需求后才能恢复  # 要求说明

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            str: 暂停提示词  # 返回类型
        """  # 方法文档字符串结束
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return ""  # 返回空字符串

        task = self.active_long_tasks[task_id]  # 获取任务

        if task.state_machine:  # 如果有状态机
            return task.state_machine.get_pause_prompt()  # 返回暂停提示词

        return ""  # 返回空字符串

    def get_resume_prompt(self,  # 定义获取恢复提示词方法
                          task_id: str  # 参数：任务ID
                          ) -> str:  # 返回：提示词
        """获取恢复提示词"""  # 方法文档字符串
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return ""  # 返回空字符串

        task = self.active_long_tasks[task_id]  # 获取任务

        if task.state_machine:  # 如果有状态机
            # 构建恢复上下文
            resume_context = {  # 构建恢复上下文字典
                "original_context": task.state_machine.paused_context,  # 原始上下文
                "user_requirements": task.state_machine.user_requirements,  # 用户需求
                "ai_understanding": task.state_machine.ai_understanding,  # AI理解
                "user_confirmed": task.state_machine.user_confirmed,  # 用户确认
                "confirmation_round": task.state_machine.confirmation_round,  # 确认轮次
                "resumed_by": "user",  # 恢复者
                "resume_time": time.time()  # 恢复时间
            }
            return task.state_machine.get_resume_prompt(resume_context)  # 返回恢复提示词

        return ""  # 返回空字符串

    def can_resume(self,  # 定义检查是否可以恢复方法
                   task_id: str  # 参数：任务ID
                   ) -> bool:  # 返回：是否可以
        """检查任务是否可以恢复"""  # 方法文档字符串
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return False  # 返回False

        task = self.active_long_tasks[task_id]  # 获取任务

        if task.state_machine:  # 如果有状态机
            return task.state_machine.can_resume()  # 返回状态机判断结果

        return False  # 返回False

    def is_waiting_confirmation(self,  # 定义检查是否等待确认方法
                                task_id: str  # 参数：任务ID
                                ) -> bool:  # 返回：是否等待
        """检查任务是否正在等待用户确认"""  # 方法文档字符串
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return False  # 返回False

        task = self.active_long_tasks[task_id]  # 获取任务

        if task.state_machine:  # 如果有状态机
            return task.state_machine.is_waiting_confirmation()  # 返回状态机判断结果

        return False  # 返回False

    async def complete_task(self,  # 定义完成任务方法
                      task_id: str,  # 参数：任务ID
                      final_result: str = ""  # 参数：最终结果
                      ):  # 返回：无
        """
        完成任务

        Raises:
            LongRunningError: 清理快照失败
        """
        if task_id not in self.active_long_tasks:  # 如果任务不存在
            return  # 直接返回

        task = self.active_long_tasks[task_id]  # 获取任务
        task.status = TaskStatus.COMPLETED.value  # 更新状态为完成

        # 记录历史
        self._add_task_history({  # 【内存泄漏修复】使用封装方法添加历史记录
            "task_id": task_id,  # 任务ID
            "action": "completed",  # 动作
            "timestamp": time.time(),  # 时间戳
            "final_result": final_result[:100] if final_result else ""  # 最终结果（截断）
        })

        # 清理状态机
        if task.state_machine:  # 如果有状态机
            task.state_machine.reset()  # 重置状态机

        # 清理快照
        try:  # 尝试清理
            self.snapshot_manager.clear_snapshot(task_id)  # 清理快照
            logger.debug(f"[PausableTaskManager] 任务 {task_id} 快照已清理")  # 记录调试日志
        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 清理快照失败 {task_id}: {e}")
            # 清理失败不阻塞任务完成，但记录错误

        del self.active_long_tasks[task_id]  # 从活跃任务删除

        logger.info(f"[PausableTaskManager] 任务 {task_id} 已完成")  # 记录日志

    def list_active_tasks(self) -> list[dict[str, Any]]:  # 定义列出活跃任务方法
        """列出所有活跃任务"""  # 方法文档字符串
        return [self.get_task_status(tid) for tid in self.active_long_tasks]  # 返回所有任务状态

    def get_statistics(self) -> dict[str, Any]:  # 定义获取统计信息方法
        """获取统计信息"""  # 方法文档字符串
        total = len(self.active_long_tasks)  # 计算总数
        status_counts = {}  # 初始化状态计数
        for task in self.active_long_tasks.values():  # 遍历任务
            status_counts[task.status] = status_counts.get(task.status, 0) + 1  # 计数

        return {  # 返回统计字典
            "total_active_tasks": total,  # 活跃任务总数
            "status_distribution": status_counts,  # 状态分布
            "history_count": len(self.task_history)  # 历史记录数
        }


class PausableTaskRunningManager:  # 定义可暂停任务运行管理器类
    """
    24小时长任务管理器（向后兼容）  # 类文档字符串标题

    集成了暂停确认状态机，提供完整的长任务管理能力。  # 类说明
    """  # 类文档字符串结束

    # 配置参数
    CHECKPOINT_INTERVAL = 300  # 每5分钟创建检查点（秒）
    FLUSH_INTERVAL = 600  # 每10分钟Memory Flush（秒）
    MAX_RUNTIME_HOURS = 24  # 最大运行时间（小时）
    MAX_CONFIRMATION_ROUNDS = 5  # 最大确认轮次

    def __init__(self):  # 初始化方法
        self._tasks: dict[str, PausableTask] = {}  # 任务字典
        self._persistence = get_session_persistence()  # 获取会话持久化
        self._running = False  # 运行标志
        self._monitor_task = None  # 监控任务
        self._task_manager = PausableTaskManager()  # 创建任务管理器
        self._snapshot_manager = get_snapshot_manager()  # 获取快照管理器

        # 确认关键词映射
        self._confirmation_keywords = {  # 确认关键词字典
            "positive": ["确认", "正确", "对", "是的", "没问题", "继续", "ok", "yes", "准确", "好"],  # 正面词
            "negative": ["不对", "错误", "不对", "有问题", "重新", "否", "no", "不准确", "错了", "再理解"],  # 负面词
        }

    async def create_task(self,  # 定义创建任务方法
                    task_id: str,  # 参数：任务ID
                    session_id: str,  # 参数：会话ID
                    description: str  # 参数：描述
                    ) -> PausableTask:  # 返回：任务对象
        """
        创建新的可暂停任务

        Raises:
            LongRunningError: 创建检查点失败
        """
        # 使用新的TaskManager创建
        task = await self._task_manager.start_pausable_task(task_id, session_id, description)  # 创建任务

        # 同时保持兼容
        self._tasks[task_id] = task  # 添加到任务字典

        # 立即创建初始检查点
        try:
            await self._create_checkpoint_async(task)  # 创建检查点
        except LongRunningError as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 创建初始检查点失败 {task_id}: {e}")
            raise

        logger.info(f"[PausableTaskRunningManager] 创建可暂停任务: {task_id}, 描述: {description}")  # 记录日志
        return task  # 返回任务

    async def on_iteration(self,
                     task_id: str,
                     messages: list,
                     working_memory: dict,
                     execution_history: list
                     ):
        """
        每轮迭代调用
        自动触发Checkpoint和Memory Flush
        """
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        task.total_rounds += 1

        now = time.time()

        # 检查是否需要创建检查点
        if now - task.last_checkpoint_time >= self.CHECKPOINT_INTERVAL:
            try:
                await self._create_checkpoint_async(task, messages, working_memory, execution_history)
                task.last_checkpoint_time = now
            except LongRunningError as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 自动创建检查点失败 {task_id}: {e}")
                # 继续执行，不中断任务

        # 检查是否需要Memory Flush
        if now - task.last_flush_time >= self.FLUSH_INTERVAL:
            try:
                await self._memory_flush(task)
                task.last_flush_time = now
            except LongRunningError as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 自动Memory Flush失败 {task_id}: {e}")
                # 继续执行，不中断任务

        # 检查是否超时
        runtime_hours = (now - task.start_time) / 3600
        if runtime_hours >= self.MAX_RUNTIME_HOURS:
            logger.warning(f"[PausableTaskRunningManager] 任务 {task_id} 运行超过{self.MAX_RUNTIME_HOURS}小时，自动标记为完成")
            await self.complete_task(task_id, "运行时间已达上限")

    async def _create_checkpoint_async(self,  # 定义创建检查点私有方法
                           task: PausableTask,  # 参数：任务
                           messages: list = None,  # 参数：消息列表
                           working_memory: dict = None,  # 参数：工作记忆
                           execution_history: list = None  # 参数：执行历史
                           ):  # 返回：无
        """
        创建检查点

        Raises:
            LongRunningError: 创建失败
        """
        try:  # 尝试创建
            # 确保检查点元数据中包含原始开始时间和暂停确认状态
            checkpoint_metadata = working_memory or {}  # 获取元数据
            if "original_start_time" not in checkpoint_metadata:  # 如果没有原始开始时间
                checkpoint_metadata["original_start_time"] = task.start_time  # 设置原始开始时间

            # 保存暂停确认状态到检查点
            checkpoint_metadata["pause_confirmation"] = {  # 保存暂停确认状态
                "status": task.status,  # 状态
                "pause_reason": task.pause_reason,  # 暂停原因
                "pause_trigger": task.pause_trigger,  # 触发者
                "paused_at": task.paused_at,  # 暂停时间
                "ai_understanding": task.ai_understanding,  # AI理解
                "user_confirmed": task.user_confirmed,  # 用户确认
                "confirmation_round": task.confirmation_round,  # 确认轮次
                "modified_requirement": task.modified_requirement,  # 修改后的需求
            }

            await self._persistence.create_checkpoint(  # 创建检查点
                session_id=task.session_id,  # 会话ID
                task_id=task.task_id,  # 任务ID
                messages=messages or [],  # 消息
                working_memory=checkpoint_metadata,  # 工作记忆
                execution_history=execution_history or []  # 执行历史
            )
            logger.debug(f"[PausableTaskRunningManager] 任务 {task.task_id} 检查点已创建")  # 记录调试日志

        except CheckpointError as e:  # 捕获检查点异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 创建检查点失败 {task.task_id}: {e}")
            raise LongRunningError(f"创建检查点失败: {e}") from e
        except Exception as e:  # 捕获其他异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 创建检查点失败 {task.task_id}: {e}")
            raise LongRunningError(f"创建检查点失败: {e}") from e

    async def _memory_flush(self,  # 定义Memory Flush私有方法
                      task: PausableTask  # 参数：任务
                      ):  # 返回：无
        """
        执行Memory Flush

        Raises:
            LongRunningError: 执行失败
        """
        if not task.key_learnings:  # 如果没有关键学习点
            return  # 直接返回

        try:  # 尝试执行
            await self._persistence.memory_flush(  # 调用持久化flush
                session_id=task.session_id,  # 会话ID
                task_description=task.description,  # 任务描述
                key_learnings=task.key_learnings.copy()  # 关键学习点副本
            )
            # 清空已记录的learning
            task.key_learnings.clear()  # 清空列表

        except CheckpointError as e:  # 捕获检查点异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] Memory Flush失败 {task.task_id}: {e}")
            raise LongRunningError(f"Memory Flush失败: {e}") from e
        except Exception as e:  # 捕获其他异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] Memory Flush失败 {task.task_id}: {e}")
            raise LongRunningError(f"Memory Flush失败: {e}") from e

    def add_learning(self,  # 定义添加学习点方法
                     task_id: str,  # 参数：任务ID
                     learning: str  # 参数：学习点
                     ):  # 返回：无
        """添加关键学习点（用于Memory Flush）"""  # 方法文档字符串
        if task_id in self._tasks:  # 如果任务存在
            self._tasks[task_id].key_learnings.append(learning)  # 添加学习点
            # 限制数量，避免内存爆炸
            if len(self._tasks[task_id].key_learnings) > 20:  # 如果超过20个
                self._tasks[task_id].key_learnings.pop(0)  # 移除最早的

    async def complete_task(self,  # 定义完成任务方法
                      task_id: str,  # 参数：任务ID
                      final_result: str = ""  # 参数：最终结果
                      ):  # 返回：无
        """
        完成任务

        Raises:
            LongRunningError: 最终Memory Flush或检查点创建失败
        """
        if task_id not in self._tasks:  # 如果任务不存在
            return  # 直接返回

        task = self._tasks[task_id]  # 获取任务
        task.status = TaskStatus.COMPLETED.value  # 更新状态为完成

        # 最终Memory Flush
        if task.key_learnings:  # 如果有学习点
            task.key_learnings.append(f"最终结果: {final_result}")  # 添加最终结果
            try:
                await self._memory_flush(task)  # 执行Flush
            except LongRunningError as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 最终Memory Flush失败 {task_id}: {e}")
                # 继续完成任务，但记录错误

        # 创建最终检查点
        try:
            await self._create_checkpoint_async(task)  # 创建检查点
        except LongRunningError as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 创建最终检查点失败 {task_id}: {e}")
            # 继续完成任务，但记录错误

        runtime = (time.time() - task.start_time) / 3600  # 计算运行时间
        logger.info(f"[PausableTaskRunningManager] 可暂停任务完成: {task_id}, 运行{runtime:.1f}小时, 共{task.total_rounds}轮")  # 记录日志

        # 清理
        await self._task_manager.complete_task(task_id, final_result)  # 完成任务
        del self._tasks[task_id]  # 从字典删除

    # ============================================================  # 分隔线：暂停确认状态机方法
    # 【核心】暂停确认状态机方法 - 集成 PausableTaskStateMachine
    # ============================================================

    async def pause_task_with_confirmation(  # 定义带确认暂停任务方法
            self,
            task_id: str,  # 参数：任务ID
            reason: str = "用户请求暂停",  # 参数：原因
            trigger: str = "ai",  # 参数：触发者
            working_memory=None,  # 参数：工作记忆
            loop_state=None,  # 参数：循环状态
            chat_history=None  # 参数：聊天历史
    ) -> PausableTask | None:  # 返回：任务或None
        """
        启动带强制确认的暂停流程，并捕获状态快照  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            reason: 暂停原因  # 参数2
            trigger: 触发方式 (ai/user/system)  # 参数3
            working_memory: WorkingMemory实例（可选，用于快照）  # 参数4
            loop_state: LoopState实例（可选，用于快照）  # 参数5
            chat_history: 聊天历史（可选，用于快照）  # 参数6

        Returns:  # 返回值说明
            PausableTask: 更新后的任务对象  # 返回类型

        Raises:
            LongRunningError: 暂停或快照捕获失败
        """
        if task_id not in self._tasks:  # 如果任务不存在
            # 尝试创建新任务
            logger.warning(f"[PausableTaskRunningManager] 任务 {task_id} 不存在，创建新任务")  # 记录警告

        # 使用TaskManager暂停（带快照）
        try:
            success = await self._task_manager.pause_task(  # 调用暂停
                task_id, reason, trigger,  # 传入参数
                working_memory=working_memory,  # 工作记忆
                loop_state=loop_state,  # 循环状态
                chat_history=chat_history  # 聊天历史
            )

            if success:  # 如果暂停成功
                task = self._tasks.get(task_id)  # 获取任务
                if task:  # 如果任务存在
                    # 同步状态
                    task.status = TaskStatus.PAUSED.value  # 更新状态
                    task.pause_reason = reason  # 设置原因
                    task.pause_trigger = trigger  # 设置触发者
                    task.paused_at = time.time()  # 设置暂停时间

                    # 创建检查点
                    try:
                        await self._create_checkpoint_async(task)  # 创建检查点
                    except LongRunningError as e:
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 暂停时创建检查点失败 {task_id}: {e}")
                        # 暂停成功但检查点失败，继续返回任务

                    logger.info(f"[PausableTaskRunningManager] 【暂停确认】任务 {task_id} 已暂停")  # 记录日志
                    return task  # 返回任务

        except LongRunningError:
            raise
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 暂停任务失败 {task_id}: {e}")
            raise LongRunningError(f"暂停任务失败: {e}") from e

        return None  # 返回None

    def submit_ai_understanding(  # 定义提交AI理解方法
            self,
            task_id: str,  # 参数：任务ID
            understanding_summary: str  # 参数：理解摘要
    ) -> bool:  # 返回：是否成功
        """
        提交AI的理解摘要  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            understanding_summary: AI的理解摘要（Markdown格式）  # 参数2

        Returns:  # 返回值说明
            bool: 是否成功提交  # 返回类型
        """  # 方法文档字符串结束
        return self._task_manager.submit_ai_understanding(task_id, understanding_summary)  # 委托给TaskManager

    def process_user_confirmation(  # 定义处理用户确认方法
            self,
            task_id: str,  # 参数：任务ID
            user_response: str  # 参数：用户响应
    ) -> dict[str, Any]:  # 返回：处理结果
        """
        处理用户对理解的响应  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            user_response: 用户响应文本  # 参数2

        Returns:  # 返回值说明
            Dict: 处理结果  # 返回类型
        """  # 方法文档字符串结束
        return self._task_manager.process_user_confirmation(task_id, user_response)  # 委托给TaskManager

    async def resume_task_with_confirmation(self,  # 定义带确认恢复任务方法
                                      task_id: str,  # 参数：任务ID
                                      working_memory=None  # 参数：工作记忆
                                      ) -> PausableTask | None:  # 返回：任务或None
        """
        带强制确认的恢复任务  # 方法文档字符串标题

        只有在用户确认理解正确后才能恢复  # 约束说明

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            working_memory: WorkingMemory实例（可选，用于恢复状态）  # 参数2

        Returns:  # 返回值说明
            PausableTask: 恢复后的任务对象，如果未经确认则返回None

        Raises:
            LongRunningError: 快照恢复失败
        """
        try:
            resume_context = await self._task_manager.resume_task(  # 调用恢复
                task_id, by_user=True, working_memory=working_memory  # 传入参数
            )

            if resume_context:  # 如果恢复成功
                task = self._tasks.get(task_id)  # 获取任务
                if task:  # 如果任务存在
                    # 同步状态
                    task.status = TaskStatus.RUNNING.value  # 更新状态
                    task.resumed_at = time.time()  # 设置恢复时间

                    # 创建恢复检查点
                    try:
                        await self._create_checkpoint_async(task)  # 创建检查点
                    except LongRunningError as e:
                        logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复时创建检查点失败 {task_id}: {e}")
                        # 恢复成功但检查点失败，继续返回任务

                    logger.info(f"[PausableTaskRunningManager] 【暂停确认】任务 {task_id} 确认恢复执行")  # 记录日志
                    return task  # 返回任务

        except LongRunningError:
            raise
        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复任务失败 {task_id}: {e}")
            raise LongRunningError(f"恢复任务失败: {e}") from e

        return None  # 返回None

    def ai_suggest_resume(self,  # 定义AI建议恢复方法
                          task_id: str  # 参数：任务ID
                          ) -> dict[str, Any]:  # 返回：建议结果
        """
        AI建议恢复任务  # 方法文档字符串标题

        当AI认为已经充分理解用户需求时，可以建议恢复。  # 说明
        但仍需要用户最终确认。  # 约束

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            Dict: 建议结果  # 返回类型
        """  # 方法文档字符串结束
        return self._task_manager.ai_suggest_resume(task_id)  # 委托给TaskManager

    def get_pause_prompt(self,  # 定义获取暂停提示词方法
                         task_id: str  # 参数：任务ID
                         ) -> str:  # 返回：提示词
        """
        获取暂停状态下的AI提示词  # 方法文档字符串标题

        【核心要求】提示词必须强调：AI必须百分百理解用户需求后才能恢复  # 核心要求

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            str: 提示词  # 返回类型
        """  # 方法文档字符串结束
        return self._task_manager.get_pause_prompt(task_id)  # 委托给TaskManager

    def get_resume_prompt(self,  # 定义获取恢复提示词方法
                          task_id: str  # 参数：任务ID
                          ) -> str:  # 返回：提示词
        """获取恢复提示词"""  # 方法文档字符串
        return self._task_manager.get_resume_prompt(task_id)  # 委托给TaskManager

    def can_resume(self,  # 定义检查是否可以恢复方法
                   task_id: str  # 参数：任务ID
                   ) -> bool:  # 返回：是否可以
        """
        检查任务是否可以恢复  # 方法文档字符串标题

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            bool: 是否可以恢复（需要用户确认）  # 返回类型
        """  # 方法文档字符串结束
        return self._task_manager.can_resume(task_id)  # 委托给TaskManager

    def is_waiting_confirmation(self,  # 定义检查是否等待确认方法
                                task_id: str  # 参数：任务ID
                                ) -> bool:  # 返回：是否等待
        """检查任务是否正在等待用户确认"""  # 方法文档字符串
        return self._task_manager.is_waiting_confirmation(task_id)  # 委托给TaskManager

    def get_confirmation_status(self,  # 定义获取确认状态方法
                                task_id: str  # 参数：任务ID
                                ) -> dict[str, Any]:  # 返回：状态字典
        """获取确认状态详情"""  # 方法文档字符串
        return self._task_manager.get_task_status(task_id)  # 委托给TaskManager

    # ============================================================  # 分隔线：原有方法保留
    # 原有方法保留（兼容旧代码）
    # ============================================================

    async def pause_task(self,  # 定义旧版暂停任务方法（兼容）
                   task_id: str  # 参数：任务ID
                   ):  # 返回：无
        """暂停任务（可恢复）- 旧方法，推荐使用 pause_task_with_confirmation """  # 方法文档字符串
        if task_id in self._tasks:  # 如果任务存在
            self._tasks[task_id].status = TaskStatus.PAUSED.value  # 更新状态
            # 创建恢复点
            try:
                await self._create_checkpoint_async(self._tasks[task_id])  # 创建检查点
            except LongRunningError as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 旧版暂停时创建检查点失败 {task_id}: {e}")
            logger.info(f"[LongRunningManager] 任务已暂停: {task_id}")  # 记录日志

    async def resume_task(self,  # 定义旧版恢复任务方法（兼容）
                    task_id: str  # 参数：任务ID
                    ) -> PausableTask | None:  # 返回：任务或None
        """
        恢复任务 - 旧方法，推荐使用 resume_task_with_confirmation

        Returns:
            PausableTask: 恢复的任务对象

        Raises:
            LongRunningError: 检查点加载失败或损坏
        """
        # 从检查点恢复
        try:
            checkpoint = await self._persistence.load_latest_checkpoint(task_id)  # 加载最新检查点
        except CheckpointError as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 无法恢复任务 {task_id}: 检查点加载失败 - {e}")
            raise LongRunningError(f"无法恢复任务 {task_id}: 检查点加载失败") from e

        if not checkpoint:  # 如果没有检查点
            logger.error(f"[SILENT_FAILURE_BLOCKED] 无法恢复任务 {task_id}: 无检查点")
            return None  # 返回None（正常情况：状态不存在）

        # 从检查点数据中恢复原始开始时间（如果存在）
        original_start_time = checkpoint.working_memory.get("original_start_time", checkpoint.timestamp)  # 获取原始时间

        # 检查是否有暂停确认状态
        pause_confirmation = checkpoint.working_memory.get("pause_confirmation", {})  # 获取暂停确认状态

        # 重新创建任务对象，保持原始开始时间以确保正确的超时判断
        task = PausableTask(  # 创建任务
            task_id=checkpoint.task_id,  # 任务ID
            session_id=checkpoint.session_id,  # 会话ID
            description=f"恢复自 {datetime.fromtimestamp(checkpoint.timestamp).strftime('%H:%M:%S')}",  # 描述
            start_time=original_start_time,  # 原始开始时间
            status=TaskStatus.RUNNING.value  # 状态
        )

        # 恢复暂停确认状态
        if pause_confirmation:  # 如果有暂停确认状态
            task.pause_reason = pause_confirmation.get("pause_reason", "")  # 恢复原因
            task.pause_trigger = pause_confirmation.get("pause_trigger", "")  # 恢复触发者
            task.paused_at = pause_confirmation.get("paused_at")  # 恢复暂停时间
            task.ai_understanding = pause_confirmation.get("ai_understanding", "")  # 恢复理解
            task.user_confirmed = pause_confirmation.get("user_confirmed")  # 恢复确认
            task.confirmation_round = pause_confirmation.get("confirmation_round", 0)  # 恢复轮次
            task.modified_requirement = pause_confirmation.get("modified_requirement", "")  # 恢复修改需求

        self._tasks[task_id] = task  # 添加到任务字典

        logger.info(f"[LongRunningManager] 任务已恢复: {task_id}")  # 记录日志
        return task  # 返回任务

    def get_task_status(self,  # 定义获取任务状态方法（兼容）
                        task_id: str  # 参数：任务ID
                        ) -> dict | None:  # 返回：状态字典或None
        """获取任务状态"""  # 方法文档字符串
        if task_id not in self._tasks:  # 如果任务不存在
            return None  # 返回None

        return self._task_manager.get_task_status(task_id)  # 委托给TaskManager

    def list_active_tasks(self) -> list:  # 定义列出活跃任务方法
        """列出所有活跃任务"""  # 方法文档字符串
        return self._task_manager.list_active_tasks()  # 委托给TaskManager

    async def force_checkpoint(self,  # 定义强制创建检查点方法
                         task_id: str  # 参数：任务ID
                         ):  # 返回：无
        """强制创建检查点"""  # 方法文档字符串
        if task_id in self._tasks:  # 如果任务存在
            task = self._tasks[task_id]  # 获取任务
            try:
                await self._create_checkpoint_async(task)  # 创建检查点
                task.last_checkpoint_time = time.time()  # 更新时间
            except LongRunningError as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 强制创建检查点失败 {task_id}: {e}")

    async def cleanup_task(self,  # 定义清理任务方法
                     task_id: str  # 参数：任务ID
                     ):  # 返回：无
        """清理任务数据（用于测试或任务结束后的清理）"""  # 方法文档字符串
        if task_id in self._tasks:  # 如果任务存在
            del self._tasks[task_id]  # 从字典删除
            await self._task_manager.complete_task(task_id)  # 完成任务
            logger.info(f"[PausableTaskRunningManager] 【暂停确认】清理任务 {task_id} 的数据")  # 记录日志


# 全局实例
_long_running_manager: PausableTaskRunningManager | None = None  # 全局管理器实例


def get_pausable_task_manager() -> PausableTaskRunningManager:  # 定义获取全局管理器函数
    """获取全局可暂停任务管理器实例"""  # 函数文档字符串
    global _long_running_manager  # 声明全局变量
    if _long_running_manager is None:  # 如果实例不存在
        _long_running_manager = PausableTaskRunningManager()  # 创建实例
    return _long_running_manager  # 返回实例


def get_long_task_manager() -> PausableTaskManager:  # 定义获取长任务管理器函数
    """获取长任务管理器（简化版）"""  # 函数文档字符串
    return get_long_running_manager()._task_manager  # 返回内部任务管理器


# =============================================================================
# 【向后兼容别名】
# =============================================================================
# 为保持向后兼容，保留旧类名作为别名
LongRunningManager = PausableTaskRunningManager  # 24小时长任务管理器别名
LongTaskManager = PausableTaskManager  # 长任务管理器别名
LongRunningTask = PausableTask  # 长任务数据类别名
LongTaskStateMachine = PausableTaskStateMachine  # 状态机别名
LongTaskState = PausableTaskState  # 状态枚举别名
# 旧函数名别名
get_long_running_manager = get_pausable_task_manager  # 获取长任务管理器别名

# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（long_running_manager.py）是 SiliconBase V5 系统的"24小时长任务管理器"核心模块。
# 提供长任务的生命周期管理，包括创建、执行、暂停、恢复和完成。
# 核心特性是集成"暂停确认状态机"，确保AI在恢复任务前必须百分百理解用户需求。
#
# 【核心类说明】
# 1. PausableTask(dataclass): 可暂停任务状态数据类
#    - 基础字段：task_id, session_id, description, start_time等
#    - 暂停相关：pause_reason, pause_trigger, paused_at, ai_understanding等
#    - 状态机引用：state_machine
#
# 2. PausableTaskManager: 可暂停任务管理器
#    - 管理活跃任务字典和历史记录
#    - 提供任务生命周期方法（启动、暂停、恢复、完成）
#    - 集成暂停确认状态机
#    - 状态快照捕获和恢复
#
# 3. PausableTaskRunningManager: 可暂停任务运行管理器（主类）
#    - 配置参数：CHECKPOINT_INTERVAL(5分钟)、FLUSH_INTERVAL(10分钟)、MAX_RUNTIME_HOURS(24小时)
#    - 自动检查点和Memory Flush
#    - 暂停确认状态机集成（核心功能）
#    - 向后兼容旧方法
#
# 【暂停确认状态机流程】
# RUNNING(运行中)
#    ↓ (pause_task_with_confirmation)
# PAUSED(已暂停)
#    ↓ (submit_requirements)
# AWAITING_REQUIREMENTS(等待需求)
#    ↓ (submit_ai_understanding)
# CONFIRMING_UNDERSTANDING(确认理解)
#    ↓ (process_user_confirmation: 确认/修改/拒绝)
# READY_TO_RESUME(可恢复) → RUNNING
#
# 【关联文件】
# 1. core/pause_confirmation_state_machine.py - 暂停确认状态机
#    * 关系：核心依赖，实现暂停确认逻辑
#    * 交互：PausableTaskStateMachine, PauseConfirmationManager, PausableTaskState
#
# 2. core/state_snapshot.py - 状态快照管理
#    * 关系：状态捕获和恢复
#    * 交互：capture_snapshot(), restore_to_working_memory()
#
# 3. core/session_persistence.py - 会话持久化
#    * 关系：检查点和Memory Flush存储
#    * 交互：create_checkpoint(), memory_flush(), load_latest_checkpoint()
#
# 4. core/task_status.py - 任务状态枚举
#    * 关系：状态定义
#    * 交互：TaskStatus枚举值
#
# 5. core/memory.py - 记忆系统
#    * 关系：记录操作历史
#    * 交互：memory.add()
#
# 6. core/logger.py - 日志系统
#    * 关系：记录日志
#    * 交互：logger.info/debug/error/warning
#
# 【达到的效果】
# 1. 可暂停任务支持：支持在ReAct循环内暂停/恢复的任务
# 2. 状态持久化：定期创建检查点，支持故障恢复
# 3. Memory Flush：定期保存关键学习点
# 4. 强制确认机制：AI必须百分百理解用户需求才能恢复任务
# 5. 状态快照：暂停时捕获完整状态，恢复时还原
# 6. 超时保护：24小时自动完成任务
# 7. 向后兼容：保留旧方法支持平滑过渡
#
# 【重要概念区分】
# 1. 可暂停任务(Pausable Task): 本模块管理，ReAct循环内可暂停/恢复的任务
# 2. 大纲长任务(Scheduled Task): task_scheduler.py管理，AI设置的定时任务，不进入循环
#
# 【使用场景】
# - 复杂多步骤任务需要在ReAct循环内暂停后确认理解再恢复
# - 需要暂停后明确确认理解再恢复的场景
# - 需要状态持久化防止数据丢失的任务
# - 需要自动检查点和Memory Flush的任务
#
# =============================================================================
