#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
【确认管理器 V1.0】异步用户确认机制
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心功能】
1. 管理待处理的确认请求
2. 异步等待用户响应（确认/拒绝/超时）
3. 支持多个并发确认请求（按session隔离）
4. 自动清理过期请求

【P0-011 修复】
- 替代 _wait_for_confirmation 的简化实现
- 真正实现异步等待用户确认
"""

import threading  # 导入线程模块
import time  # 导入时间模块
from dataclasses import dataclass, field  # 导入数据类装饰器
from enum import Enum  # 导入枚举类
from typing import Any  # 导入类型注解

from core.logger import logger  # 导入日志记录器


class ConfirmStatus(Enum):  # 确认状态枚举类
    """确认状态枚举"""  # 类文档字符串
    PENDING = "pending"      # 等待中
    CONFIRMED = "confirmed"  # 用户已确认
    REJECTED = "rejected"    # 用户已拒绝
    TIMEOUT = "timeout"      # 超时
    CANCELLED = "cancelled"  # 已取消


@dataclass  # 数据类装饰器
class ConfirmRequest:  # 确认请求数据类
    """确认请求数据"""  # 类文档字符串
    request_id: str  # 请求唯一标识
    session_id: str  # 会话ID
    tool_id: str  # 工具ID
    reason: str  # 确认原因
    timeout_seconds: int  # 超时时间（秒）
    created_at: float = field(default_factory=time.time)  # 创建时间，默认当前时间
    status: ConfirmStatus = ConfirmStatus.PENDING  # 状态，默认等待中
    response_data: dict[str, Any] | None = None  # 响应数据

    def __post_init__(self):  # 初始化后处理
        """计算超时时间"""  # 方法文档字符串
        self.expires_at = self.created_at + self.timeout_seconds  # 计算过期时间

    def is_expired(self) -> bool:  # 检查是否过期方法
        """检查是否已过期"""  # 方法文档字符串
        return time.time() > self.expires_at  # 当前时间是否超过过期时间

    def to_dict(self) -> dict[str, Any]:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "request_id": self.request_id,  # 请求ID
            "session_id": self.session_id,  # 会话ID
            "tool_id": self.tool_id,  # 工具ID
            "reason": self.reason,  # 原因
            "timeout_seconds": self.timeout_seconds,  # 超时时间
            "created_at": self.created_at,  # 创建时间
            "expires_at": self.expires_at,  # 过期时间
            "status": self.status.value,  # 状态值
            "response_data": self.response_data  # 响应数据
        }


class ConfirmationManager:  # 确认管理器类
    """
    确认管理器 - 单例模式

    管理所有待处理的确认请求，支持：
    - 创建确认请求
    - 等待用户响应（异步）
    - 处理用户响应（确认/拒绝）
    - 自动超时处理
    """

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 单例锁

    def __new__(cls):  # 单例控制
        if cls._instance is None:  # 实例不存在
            with cls._lock:  # 获取锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        if self._initialized:  # 已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

        # 存储所有确认请求: request_id -> ConfirmRequest  # 注释：请求存储
        self._requests: dict[str, ConfirmRequest] = {}  # 请求字典

        # 按session分组: session_id -> set(request_id)  # 注释：会话分组
        self._session_requests: dict[str, set] = {}  # 会话请求映射

        # 用于通知等待线程的Condition: request_id -> Condition  # 注释：条件变量
        self._conditions: dict[str, threading.Condition] = {}  # 条件变量字典

        # 锁  # 注释：线程锁
        self._lock = threading.RLock()  # 可重入锁

        # 启动清理线程  # 注释：启动守护线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True, name="ConfirmCleanup")  # 创建清理线程
        self._cleanup_thread.start()  # 启动线程

        logger.info("[ConfirmationManager] 确认管理器初始化完成")  # 记录日志

    def create_request(  # 创建确认请求方法
        self,
        session_id: str,
        tool_id: str,
        reason: str,
        timeout_seconds: int = 10
    ) -> str:
        """
        创建新的确认请求

        Args:
            session_id: 会话ID
            tool_id: 工具ID
            reason: 确认原因
            timeout_seconds: 超时时间（秒）

        Returns:
            request_id: 请求唯一标识
        """
        import uuid  # 导入UUID模块

        request_id = f"{session_id}_{tool_id}_{uuid.uuid4().hex[:8]}"  # 生成请求ID

        request = ConfirmRequest(  # 创建请求对象
            request_id=request_id,  # 请求ID
            session_id=session_id,  # 会话ID
            tool_id=tool_id,  # 工具ID
            reason=reason,  # 原因
            timeout_seconds=timeout_seconds  # 超时时间
        )

        with self._lock:  # 获取锁
            self._requests[request_id] = request  # 保存请求

            if session_id not in self._session_requests:  # 会话不存在
                self._session_requests[session_id] = set()  # 创建集合
            self._session_requests[session_id].add(request_id)  # 添加请求ID

            # 创建Condition对象用于等待  # 注释：创建条件变量
            self._conditions[request_id] = threading.Condition(self._lock)  # 创建条件变量

        logger.info(f"[ConfirmationManager] 创建确认请求: {request_id}, 超时: {timeout_seconds}秒")  # 记录日志
        return request_id  # 返回请求ID

    def wait_for_response(  # 等待响应方法
        self,
        request_id: str,
        check_interval: float = 0.1
    ) -> bool:
        """
        等待用户响应（阻塞式）

        Args:
            request_id: 请求ID
            check_interval: 检查间隔（秒）

        Returns:
            bool: True=确认, False=拒绝或超时
        """
        with self._lock:  # 获取锁
            if request_id not in self._requests:  # 请求不存在
                logger.error(f"[ConfirmationManager] 请求不存在: {request_id}")  # 记录错误
                return False  # 返回失败

            request = self._requests[request_id]  # 获取请求
            condition = self._conditions.get(request_id)  # 获取条件变量

            if not condition:  # 条件变量不存在
                logger.error(f"[ConfirmationManager] Condition不存在: {request_id}")  # 记录错误
                return False  # 返回失败

        # 等待响应或超时  # 注释：等待逻辑
        start_time = time.time()  # 记录开始时间
        timeout = request.timeout_seconds  # 获取超时时间

        with condition:  # 使用条件变量
            while request.status == ConfirmStatus.PENDING:  # 状态为等待中
                remaining = timeout - (time.time() - start_time)  # 计算剩余时间
                if remaining <= 0:  # 已超时
                    # 超时  # 注释：超时处理
                    with self._lock:  # 获取锁
                        request.status = ConfirmStatus.TIMEOUT  # 更新状态为超时
                    logger.info(f"[ConfirmationManager] 请求超时: {request_id}")  # 记录日志
                    return False  # 返回失败

                # 等待信号或超时  # 注释：条件等待
                condition.wait(timeout=remaining)  # 等待

                # 检查状态  # 注释：状态检查
                if request.status == ConfirmStatus.CONFIRMED:  # 已确认
                    logger.info(f"[ConfirmationManager] 请求已确认: {request_id}")  # 记录日志
                    return True  # 返回成功
                elif request.status == ConfirmStatus.REJECTED:  # 已拒绝
                    logger.info(f"[ConfirmationManager] 请求被拒绝: {request_id}")  # 记录日志
                    return False  # 返回失败
                elif request.status == ConfirmStatus.CANCELLED:  # 已取消
                    logger.info(f"[ConfirmationManager] 请求已取消: {request_id}")  # 记录日志
                    return False  # 返回失败

        # 到这里应该是超时  # 注释：默认返回
        return False  # 返回失败

    def confirm(self, request_id: str, response_data: dict[str, Any] = None) -> bool:  # 确认方法
        """
        确认请求（用户点击确认）

        Args:
            request_id: 请求ID
            response_data: 额外响应数据

        Returns:
            bool: 是否成功
        """
        with self._lock:  # 获取锁
            if request_id not in self._requests:  # 请求不存在
                logger.warning(f"[ConfirmationManager] 确认失败，请求不存在: {request_id}")  # 记录警告
                return False  # 返回失败

            request = self._requests[request_id]  # 获取请求

            if request.status != ConfirmStatus.PENDING:  # 状态不是等待中
                logger.warning(f"[ConfirmationManager] 确认失败，请求状态: {request.status.value}")  # 记录警告
                return False  # 返回失败

            request.status = ConfirmStatus.CONFIRMED  # 更新状态为已确认
            request.response_data = response_data or {}  # 保存响应数据

            # 通知等待线程  # 注释：通知机制
            condition = self._conditions.get(request_id)  # 获取条件变量
            if condition:  # 存在
                with condition:  # 获取条件锁
                    condition.notify_all()  # 通知所有等待线程

        logger.info(f"[ConfirmationManager] 请求已确认: {request_id}")  # 记录日志
        return True  # 返回成功

    def reject(self, request_id: str, reason: str = None) -> bool:  # 拒绝方法
        """
        拒绝请求（用户点击拒绝）

        Args:
            request_id: 请求ID
            reason: 拒绝原因

        Returns:
            bool: 是否成功
        """
        with self._lock:  # 获取锁
            if request_id not in self._requests:  # 请求不存在
                logger.warning(f"[ConfirmationManager] 拒绝失败，请求不存在: {request_id}")  # 记录警告
                return False  # 返回失败

            request = self._requests[request_id]  # 获取请求

            if request.status != ConfirmStatus.PENDING:  # 状态不是等待中
                logger.warning(f"[ConfirmationManager] 拒绝失败，请求状态: {request.status.value}")  # 记录警告
                return False  # 返回失败

            request.status = ConfirmStatus.REJECTED  # 更新状态为已拒绝
            request.response_data = {"reject_reason": reason}  # 保存拒绝原因

            # 通知等待线程  # 注释：通知机制
            condition = self._conditions.get(request_id)  # 获取条件变量
            if condition:  # 存在
                with condition:  # 获取条件锁
                    condition.notify_all()  # 通知所有等待线程

        logger.info(f"[ConfirmationManager] 请求被拒绝: {request_id}, 原因: {reason}")  # 记录日志
        return True  # 返回成功

    def cancel(self, request_id: str) -> bool:  # 取消方法
        """
        取消请求

        Args:
            request_id: 请求ID

        Returns:
            bool: 是否成功
        """
        with self._lock:  # 获取锁
            if request_id not in self._requests:  # 请求不存在
                return False  # 返回失败

            request = self._requests[request_id]  # 获取请求
            request.status = ConfirmStatus.CANCELLED  # 更新状态为已取消

            # 通知等待线程  # 注释：通知机制
            condition = self._conditions.get(request_id)  # 获取条件变量
            if condition:  # 存在
                with condition:  # 获取条件锁
                    condition.notify_all()  # 通知所有等待线程

        logger.info(f"[ConfirmationManager] 请求已取消: {request_id}")  # 记录日志
        return True  # 返回成功

    def get_request(self, request_id: str) -> ConfirmRequest | None:  # 获取请求方法
        """获取请求信息"""  # 方法文档字符串
        with self._lock:  # 获取锁
            return self._requests.get(request_id)  # 返回请求

    def get_session_pending_requests(self, session_id: str) -> list:  # 获取会话待处理请求方法
        """获取会话的所有待处理请求"""  # 方法文档字符串
        with self._lock:  # 获取锁
            request_ids = self._session_requests.get(session_id, set())  # 获取请求ID集合
            return [  # 返回请求列表
                self._requests[rid] for rid in request_ids  # 遍历ID
                if rid in self._requests and self._requests[rid].status == ConfirmStatus.PENDING  # 检查状态和存在性
            ]

    def cleanup_session(self, session_id: str):  # 清理会话方法
        """清理会话的所有请求"""  # 方法文档字符串
        with self._lock:  # 获取锁
            request_ids = self._session_requests.get(session_id, set()).copy()  # 复制请求ID集合
            for rid in request_ids:  # 遍历请求ID
                self._remove_request(rid)  # 移除请求
            if session_id in self._session_requests:  # 会话存在
                del self._session_requests[session_id]  # 删除会话

        logger.info(f"[ConfirmationManager] 清理会话: {session_id}")  # 记录日志

    def _remove_request(self, request_id: str):  # 内部移除请求方法
        """内部方法：移除请求"""  # 方法文档字符串
        if request_id in self._requests:  # 请求存在
            request = self._requests[request_id]  # 获取请求
            session_id = request.session_id  # 获取会话ID

            # 从会话集合中移除  # 注释：清理会话映射
            if session_id in self._session_requests:  # 会话存在
                self._session_requests[session_id].discard(request_id)  # 从集合中移除

            # 移除请求和Condition  # 注释：清理资源
            del self._requests[request_id]  # 删除请求
            if request_id in self._conditions:  # 条件变量存在
                del self._conditions[request_id]  # 删除条件变量

    def _cleanup_loop(self):  # 清理循环方法
        """清理过期请求的守护线程"""  # 方法文档字符串
        while True:  # 无限循环
            try:  # 异常处理
                time.sleep(5)  # 每5秒检查一次  # 休眠5秒

                with self._lock:  # 获取锁
                    expired_ids = []  # 过期请求ID列表
                    for request_id, request in self._requests.items():  # 遍历所有请求
                        if request.status == ConfirmStatus.PENDING and request.is_expired():  # 等待中且已过期
                            request.status = ConfirmStatus.TIMEOUT  # 更新状态为超时
                            expired_ids.append(request_id)  # 添加到过期列表

                            # 通知等待线程  # 注释：通知机制
                            condition = self._conditions.get(request_id)  # 获取条件变量
                            if condition:  # 存在
                                with condition:  # 获取条件锁
                                    condition.notify_all()  # 通知所有等待线程

                    # 清理已完成的请求（保留一段时间用于查询）  # 注释：清理已完成请求
                    completed_statuses = {ConfirmStatus.CONFIRMED, ConfirmStatus.REJECTED,
                                         ConfirmStatus.TIMEOUT, ConfirmStatus.CANCELLED}  # 已完成状态集合
                    current_time = time.time()  # 当前时间
                    for request_id, request in list(self._requests.items()):  # 遍历所有请求（复制列表）
                        if request.status in completed_statuses and current_time - request.created_at > 300:  # 状态为已完成且超过5分钟
                            self._remove_request(request_id)  # 移除请求

                    if expired_ids:  # 有过期请求
                        logger.info(f"[ConfirmationManager] 清理过期请求: {len(expired_ids)}个")  # 记录日志

            except Exception as e:  # 捕获异常
                logger.error(f"[ConfirmationManager] 清理循环异常: {e}")  # 记录错误

    def get_stats(self) -> dict[str, Any]:  # 获取统计方法
        """获取统计信息"""  # 方法文档字符串
        with self._lock:  # 获取锁
            pending = sum(1 for r in self._requests.values() if r.status == ConfirmStatus.PENDING)  # 统计等待中
            confirmed = sum(1 for r in self._requests.values() if r.status == ConfirmStatus.CONFIRMED)  # 统计已确认
            rejected = sum(1 for r in self._requests.values() if r.status == ConfirmStatus.REJECTED)  # 统计已拒绝
            timeout = sum(1 for r in self._requests.values() if r.status == ConfirmStatus.TIMEOUT)  # 统计超时

            return {  # 返回统计字典
                "total_requests": len(self._requests),  # 总请求数
                "pending": pending,  # 等待中
                "confirmed": confirmed,  # 已确认
                "rejected": rejected,  # 已拒绝
                "timeout": timeout,  # 超时
                "active_sessions": len(self._session_requests)  # 活跃会话数
            }


# 全局实例
confirmation_manager = ConfirmationManager()  # 创建确认管理器全局实例


def wait_for_user_confirmation(  # 等待用户确认便捷函数
    session_id: str,
    tool_id: str,
    reason: str,
    timeout_seconds: int = 10,
    send_callback: callable = None
) -> bool:
    """
    便捷函数：等待用户确认

    Args:
        session_id: 会话ID
        tool_id: 工具ID
        reason: 确认原因（显示给用户）
        timeout_seconds: 超时时间
        send_callback: 发送确认请求的回调函数，接收request_id和request_data

    Returns:
        bool: True=用户确认, False=拒绝或超时
    """
    # 创建确认请求  # 注释：创建请求
    request_id = confirmation_manager.create_request(  # 调用创建方法
        session_id=session_id,  # 会话ID
        tool_id=tool_id,  # 工具ID
        reason=reason,  # 原因
        timeout_seconds=timeout_seconds  # 超时时间
    )

    # 发送确认请求到前端（通过回调）  # 注释：发送请求
    if send_callback:  # 回调存在
        try:  # 异常处理
            request = confirmation_manager.get_request(request_id)  # 获取请求
            send_callback(request_id, request.to_dict())  # 调用回调
        except Exception as e:  # 捕获异常
            logger.error(f"[wait_for_user_confirmation] 发送确认请求失败: {e}")  # 记录错误
            confirmation_manager.cancel(request_id)  # 取消请求
            return False  # 返回失败

    # 等待响应  # 注释：等待响应
    result = confirmation_manager.wait_for_response(request_id)  # 调用等待方法

    return result  # 返回结果


__all__ = [  # 公开接口列表
    'ConfirmationManager',  # 确认管理器类
    'confirmation_manager',  # 全局实例
    'ConfirmRequest',  # 确认请求类
    'ConfirmStatus',  # 确认状态枚举
    'wait_for_user_confirmation'  # 便捷函数
]


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"确认管理器"，实现异步用户确认机制。
# 用于敏感操作（如危险工具调用）前向用户请求确认。
#
# 【核心功能】
# 1. 确认请求管理：创建、查询、清理确认请求
# 2. 异步等待：阻塞式等待用户响应（确认/拒绝/超时）
# 3. 多请求支持：按session隔离，支持并发确认请求
# 4. 自动超时：可配置超时时间，自动处理超时请求
# 5. 自动清理：定期清理已完成和过期的请求
#
# 【确认状态】
# - PENDING: 等待中
# - CONFIRMED: 用户已确认
# - REJECTED: 用户已拒绝
# - TIMEOUT: 超时
# - CANCELLED: 已取消
#
# 【使用场景】
# - 危险工具调用前确认
# - 重要操作前的二次确认
# - 需要用户授权的场景
#
# 【关联文件】
# - core/tool_manager.py: 工具管理，触发确认
# - core/agent_loop.py: Agent循环，等待确认结果
# =============================================================================
