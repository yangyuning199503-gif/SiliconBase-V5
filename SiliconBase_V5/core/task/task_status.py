#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
SiliconBase V5 - 统一任务状态定义  # 模块标题

所有任务相关的状态枚举都应该从这里导入，避免多处定义导致的混乱。  # 设计目的

使用方式:  # 使用示例
    from core.task.task_status import TaskStatus, TERMINAL_STATUSES  # 导入示例1

    if task.status == TaskStatus.PENDING:  # 使用示例2
        ...  # 代码

    if task.status in TERMINAL_STATUSES:  # 使用示例3
        ...  # 代码

作者: TaskStatus-Unifier  # 作者
日期: 2026-02-28  # 日期
"""  # 文档字符串结束

from enum import Enum  # 从enum导入枚举基类


class TaskStatus(str, Enum):  # 定义任务状态枚举类，继承str和Enum
    """  # 类文档字符串开始
    统一任务状态枚举  # 类功能

    继承str和Enum，可以直接与字符串比较，也可以使用.value获取字符串值。  # 特性说明

    状态流转:  # 状态流转图
    PENDING → READY → RUNNING → [COMPLETED/FAILED/CANCELLED] → ARCHIVED  # 主要流转
           ↘ PAUSED → RUNNING  # 暂停恢复流转
    """  # 类文档字符串结束
    # 初始状态  # 注释：初始状态
    PENDING = "pending"           # 待处理  # 待处理状态
    READY = "ready"               # 已准备好，等待执行  # 就绪状态

    # 运行状态  # 注释：运行状态
    RUNNING = "running"           # 运行中  # 运行中状态
    PAUSED = "paused"             # 已暂停（长任务模式）  # 暂停状态

    # 终态  # 注释：终态
    COMPLETED = "completed"       # 已完成  # 完成状态
    FAILED = "failed"             # 失败  # 失败状态
    CANCELLED = "cancelled"       # 已取消  # 取消状态
    ARCHIVED = "archived"         # 已归档  # 归档状态

    # 长任务特有状态（暂停确认状态机）  # 注释：长任务特有状态
    AWAITING_CONFIRMATION = "awaiting_confirmation"         # 等待用户确认理解  # 等待确认
    CONFIRMING_UNDERSTANDING = "confirming_understanding"   # AI确认理解中（输出理解摘要）  # 确认理解中
    CONFIRMED = "confirmed"                                 # 理解已确认，准备恢复  # 已确认
    INTERRUPTED = "interrupted"                             # 已中断  # 中断状态

    # 向后兼容的别名（已废弃，请使用新名称）  # 注释：兼容性别名
    AWAITING_REQUIREMENTS = "awaiting_confirmation"         # 兼容旧代码  # 旧名兼容
    READY_TO_RESUME = "confirmed"                           # 兼容旧代码  # 旧名兼容

    @property  # 属性装饰器
    def is_terminal(self) -> bool:  # 定义是否终态属性
        """是否为终态"""  # 属性文档字符串
        return self in _TERMINAL_SET  # 检查是否在终态集合中

    @property  # 属性装饰器
    def is_archivable(self) -> bool:  # 定义是否可归档属性
        """是否可归档"""  # 属性文档字符串
        return self in _ARCHIVABLE_SET  # 检查是否在可归档集合中

    def can_transition_to(self, new_status: 'TaskStatus') -> bool:  # 定义状态转换检查方法
        """检查是否可以转换到目标状态"""  # 方法文档字符串
        # 终态不能转换到其他状态（除了归档）  # 注释：终态限制
        if self.is_terminal and new_status != TaskStatus.ARCHIVED:  # 如果是终态且不是归档
            return False  # 返回False
        # 已归档不能转换  # 注释：归档限制
        return self != TaskStatus.ARCHIVED  # 如果已归档返回False，否则允许转换


# 终态集合（用于快速判断）  # 注释：终态集合
_TERMINAL_SET = {  # 定义终态集合
    TaskStatus.COMPLETED,  # 已完成
    TaskStatus.FAILED,  # 失败
    TaskStatus.CANCELLED,  # 已取消
    TaskStatus.ARCHIVED  # 已归档
}  # 集合结束

# 可归档状态集合  # 注释：可归档集合
_ARCHIVABLE_SET = {  # 定义可归档集合
    TaskStatus.COMPLETED,  # 已完成
    TaskStatus.FAILED,  # 失败
    TaskStatus.CANCELLED  # 已取消
}  # 集合结束

# 字符串列表（用于数据库查询等）  # 注释：字符串列表
TERMINAL_STATUSES: list[str] = [s.value for s in _TERMINAL_SET]  # 终态字符串列表  # 终态列表
ARCHIVABLE_STATUSES: list[str] = [s.value for s in _ARCHIVABLE_SET]  # 可归档字符串列表  # 可归档列表

# 活跃状态（非终态）  # 注释：活跃状态
ACTIVE_STATUSES: list[str] = [  # 定义活跃状态列表
    TaskStatus.PENDING.value,  # 待处理
    TaskStatus.READY.value,  # 就绪
    TaskStatus.RUNNING.value,  # 运行中
    TaskStatus.PAUSED.value,  # 暂停
    TaskStatus.AWAITING_CONFIRMATION.value,  # 等待确认
    TaskStatus.CONFIRMING_UNDERSTANDING.value,  # 确认理解中
    TaskStatus.CONFIRMED.value  # 已确认
]  # 列表结束

# 可执行状态（可以开始执行）  # 注释：可执行状态
EXECUTABLE_STATUSES: list[str] = [  # 定义可执行状态列表
    TaskStatus.READY.value,  # 就绪
    TaskStatus.PAUSED.value  # 暂停后可以恢复执行  # 暂停也可执行
]  # 列表结束


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"统一任务状态定义模块"，集中定义所有任务相关的
# 状态枚举，避免多处定义导致的混乱和不一致。
#
# 【核心设计】
# 1. 继承str+Enum: 既可以直接与字符串比较，也可以使用.value获取字符串值
# 2. 状态属性: is_terminal判断是否终态，is_archivable判断是否可归档
# 3. 状态转换检查: can_transition_to()方法验证状态转换合法性
# 4. 预设状态集合: _TERMINAL_SET、_ARCHIVABLE_SET等用于快速判断
# 5. 兼容性别名: 保留旧状态名(AWAITING_REQUIREMENTS等)确保向后兼容
#
# 【关联文件】
# - core/task_queue.py            : 使用TaskStatus管理任务状态
# - core/task_orchestrator.py     : 使用状态集合判断任务是否完成
# - core/interrupt_handler.py     : 使用INTERRUPTED等状态
# - core/task_scheduler.py        : 使用状态判断任务是否可执行
# - 数据库模型                    : 使用TERMINAL_STATUSES查询终态任务
#
# 【状态分类】
# - 初始状态: PENDING(待处理), READY(就绪)
# - 运行状态: RUNNING(运行中), PAUSED(暂停)
# - 终态: COMPLETED(完成), FAILED(失败), CANCELLED(取消), ARCHIVED(归档)
# - 长任务特有: AWAITING_CONFIRMATION(等待确认), CONFIRMING_UNDERSTANDING(确认中), CONFIRMED(已确认)
#
# 【状态流转】
# PENDING → READY → RUNNING → [COMPLETED/FAILED/CANCELLED] → ARCHIVED
#          ↘ PAUSED → RUNNING
#
# 【使用建议】
# - 判断任务是否完成: task.status.is_terminal
# - 判断任务是否可以执行: task.status.value in EXECUTABLE_STATUSES
# - 数据库查询终态任务: status in TERMINAL_STATUSES
# =============================================================================
