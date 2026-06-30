#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
增强安全层 V5.1 - 多租户安全管理
核心功能：
- 多租户安全管理器（MultiTenantSecurityManager）
- 统一授权流程
- 安全审计日志
- 动态风险响应

架构设计：
  ┌─────────────────────────────────────────┐
  │     MultiTenantSecurityManager          │
  │  ┌─────────────┐    ┌────────────────┐  │
  │  │ SafetyGuard │◄──►│  PolicyCenter  │  │
  │  └─────────────┘    └────────────────┘  │
  │         │                    │          │
  │         └────────┬───────────┘          │
  │                  ▼                      │
  │         ┌─────────────────┐             │
  │         │ Authorization   │             │
  │         │     Engine      │             │
  │         └─────────────────┘             │
  └─────────────────────────────────────────┘

2026-02-26 创建：多租户安全隔离、统一授权接口、完整审计追踪
"""  # 模块文档字符串：说明核心功能、架构和版本信息
import asyncio  # asyncio模块：用于异步处理确认请求和延迟清理
import threading  # threading模块：用于实现单例模式的线程锁
import time  # time模块：用于计算操作耗时和确认请求超时
from collections.abc import Callable  # 类型注解：支持复杂类型定义
from dataclasses import dataclass, field  # dataclass装饰器和field函数
from datetime import datetime  # datetime类：用于记录审计日志时间戳
from enum import Enum  # Enum类：用于定义授权状态枚举
from typing import Any

from core.diagnostic import safe_create_task
from core.logger import logger  # 导入日志记录器：记录安全事件
from core.memory.memory_service import get_memory_service  # 【P1-迁移】异步记忆服务入口
from core.safety.safety_guard import RiskLevel, safety_guard  # 导入安全守卫相关类和实例
from core.strategy.policy import policy_center  # 导入策略中心相关类和实例


class AuthorizationStatus(Enum):  # 授权状态枚举类：定义操作授权的各种状态
    """授权状态枚举"""  # 类文档字符串
    ALLOWED = "allowed"  # 已允许：操作被授权执行
    DENIED = "denied"  # 已拒绝：操作被禁止执行
    PENDING = "pending"  # 待处理：等待用户确认中
    CONFIRMATION_REQUIRED = "confirmation_required"  # 需要确认：需要用户显式确认


@dataclass  # 使用@dataclass自动生成__init__等方法
class AuthorizationResult:  # 授权结果类：封装授权操作的返回结果
    """授权结果"""  # 类文档字符串
    status: AuthorizationStatus  # 授权状态：枚举值表示授权结果
    denied: bool = False  # 是否被拒绝：True表示操作被拒绝
    reason: str = ""  # 拒绝/允许原因：说明授权决策的理由
    risk_level: RiskLevel | None = None  # 风险等级：评估的风险级别（如有）
    confirmation_token: str | None = None  # 确认令牌：用于异步确认流程的标识
    audit_log_id: str | None = None  # 审计日志ID：关联的审计记录标识
    requires_confirmation: bool = False  # 是否需要确认：兼容性属性，标记是否需要用户确认

    def __post_init__(self):  # 初始化后处理方法：dataclass特性，在__init__后自动调用
        """初始化后处理"""  # 方法文档字符串
        self.requires_confirmation = self.status == AuthorizationStatus.CONFIRMATION_REQUIRED  # 状态为需要确认时设为True


@dataclass  # 使用@dataclass简化类定义
class SecurityAuditLog:  # 安全审计日志类：记录安全相关操作的详细信息
    """安全审计日志"""  # 类文档字符串
    log_id: str  # 日志ID：唯一标识一条审计记录
    user_id: str  # 用户ID：操作执行者
    tool_name: str  # 工具名称：被调用的工具
    params: dict[str, Any]  # 工具参数：调用时传入的参数
    context: dict[str, Any]  # 上下文信息：请求来源等附加信息
    decision: str  # 决策结果：allowed/denied/confirmed/rejected之一
    reason: str  # 决策原因：说明为何做出该决策
    risk_level: str | None  # 风险等级：字符串形式的风险级别
    timestamp: datetime = field(default_factory=datetime.now)  # 时间戳：记录创建时间，默认为当前时间
    duration_ms: float = 0.0  # 耗时毫秒数：授权流程执行耗时

    def to_dict(self) -> dict[str, Any]:  # 转换为字典方法：用于序列化存储
        """转换为字典"""  # 方法文档字符串
        return {  # 返回包含所有字段的字典
            "log_id": self.log_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "params": self.params,
            "context": self.context,
            "decision": self.decision,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "timestamp": self.timestamp.isoformat(),  # datetime转ISO格式字符串便于JSON序列化
            "duration_ms": self.duration_ms
        }


class ConfirmationManager:  # 确认请求管理器类：管理需要用户确认的操作请求
    """确认请求管理器"""  # 类文档字符串

    def __init__(self, timeout_seconds: int = 60):  # 初始化方法
        self._pending_confirmations: dict[str, dict] = {}  # 待处理确认字典：token -> 请求信息
        self._timeout_seconds = timeout_seconds  # 超时时间：确认请求的有效期（秒），默认60秒
        self._lock = False  # 简单锁标志：用于防止并发修改（当前使用简单标志而非完整锁）

    def create_request(  # 创建确认请求方法
        self,
        user_id: str,  # 用户ID：请求发起人
        tool_name: str,  # 工具名称：需要确认的工具
        params: dict,  # 工具参数：调用参数
        reason: str,  # 确认原因：说明为何需要确认
        risk_level: RiskLevel  # 风险等级：评估的风险级别
    ) -> str:  # 返回确认令牌
        """创建确认请求"""  # 方法文档字符串
        import uuid  # 导入uuid模块：用于生成唯一标识符
        token = str(uuid.uuid4())  # 生成UUID作为确认令牌

        self._pending_confirmations[token] = {  # 存储确认请求信息
            "user_id": user_id,
            "tool_name": tool_name,
            "params": params,
            "reason": reason,
            "risk_level": risk_level,
            "created_at": time.time(),  # 创建时间戳
            "status": "pending"  # 初始状态为待处理
        }

        return token  # 返回令牌供后续查询使用

    def get_request(self, token: str) -> dict | None:  # 获取确认请求方法
        """获取确认请求"""  # 方法文档字符串
        request = self._pending_confirmations.get(token)  # 从字典获取请求
        if not request:  # 请求不存在
            return None  # 返回None

        # 检查是否过期
        if time.time() - request["created_at"] > self._timeout_seconds:  # 当前时间减创建时间超过超时时间
            del self._pending_confirmations[token]  # 删除过期请求
            return None  # 返回None表示已过期

        return request  # 返回请求信息

    def confirm(self, token: str, confirmed: bool) -> bool:  # 处理确认结果方法
        """处理确认结果"""  # 方法文档字符串
        request = self.get_request(token)  # 获取请求（会自动检查过期）
        if not request:  # 请求不存在或已过期
            return False  # 返回失败

        request["status"] = "confirmed" if confirmed else "rejected"  # 更新状态
        request["confirmed"] = confirmed  # 记录确认结果
        request["resolved_at"] = time.time()  # 记录处理时间戳

        # 延迟清理（保留一段时间用于审计）
        safe_create_task(self._cleanup_after_delay(token, 300), name="_cleanup_after_delay")  # 5分钟后清理

        return True  # 返回成功

    async def _cleanup_after_delay(self, token: str, delay_seconds: int):  # 延迟清理方法
        """延迟清理"""  # 方法文档字符串
        await asyncio.sleep(delay_seconds)  # 异步等待指定秒数
        if token in self._pending_confirmations:  # 检查令牌是否仍存在
            del self._pending_confirmations[token]  # 删除确认请求

    def is_confirmed(self, token: str) -> bool | None:  # 检查确认状态方法
        """检查确认状态"""  # 方法文档字符串
        request = self._pending_confirmations.get(token)  # 获取请求
        if not request:  # 请求不存在
            return None  # 返回None

        if request.get("status") in ["confirmed", "rejected"]:  # 如果已处理（确认或拒绝）
            return request.get("confirmed")  # 返回确认结果（True/False）

        return None  # 仍在等待中，返回None

    def cleanup_expired(self):  # 清理过期请求方法
        """清理过期请求"""  # 方法文档字符串
        now = time.time()  # 获取当前时间戳
        expired = [  # 找出所有过期的待处理请求
            token for token, req in self._pending_confirmations.items()
            if now - req["created_at"] > self._timeout_seconds  # 超过超时时间
            and req.get("status") == "pending"  # 且状态仍为待处理
        ]
        for token in expired:  # 遍历过期令牌
            del self._pending_confirmations[token]  # 删除过期请求


class MultiTenantSecurityManager:  # 多租户安全管理器类：核心安全管理组件
    """
    多租户安全管理器
    【核心功能】
    - 统一授权流程
    - 用户级安全隔离
    - 安全审计日志
    - 动态风险响应
    """  # 类文档字符串

    _instance = None  # 单例实例引用
    _lock = threading.Lock()  # 线程锁：用于单例创建的线程安全

    def __new__(cls):  # 重写new方法实现单例模式
        if cls._instance is None:  # 检查实例是否已存在
            with cls._lock:  # 获取线程锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回单例实例

    def __init__(self):  # 初始化方法
        if hasattr(self, '_initialized') and self._initialized:  # 检查是否已初始化
            return  # 已初始化则直接返回
        self._initialized = True  # 标记已初始化

        self.safety_guard = safety_guard  # 安全守卫实例：用于风险评估
        self.policy_center = policy_center  # 策略中心实例：用于策略检查
        self.confirmation_manager = ConfirmationManager()  # 确认管理器：管理确认流程
        self._memory_manager = None  # 【P1-迁移】记忆管理器已废弃，改用 get_memory_service

        # 审计日志回调
        self._audit_callbacks: list[Callable] = []  # 回调列表：存储审计日志处理回调

        # 确认请求回调（用于UI交互）
        self._confirmation_callback: Callable | None = None  # 确认回调：用于触发UI确认对话框

        logger.info("[MultiTenantSecurityManager] 多租户安全管理器初始化完成")  # 记录初始化日志

    def set_confirmation_callback(self, callback: Callable[[str, str, dict, str], asyncio.Future]):  # 设置确认回调方法
        """
        设置确认请求回调
        Args:
            callback: 回调函数，接收(user_id, tool_name, params, reason)返回Future
        """  # 方法文档字符串
        self._confirmation_callback = callback  # 保存回调函数

    def register_audit_callback(self, callback: Callable[[SecurityAuditLog], None]):  # 注册审计回调方法
        """
        注册审计日志回调
        Args:
            callback: 审计日志回调函数
        """  # 方法文档字符串
        self._audit_callbacks.append(callback)  # 添加到回调列表

    async def _log_audit(self, log: SecurityAuditLog):  # 记录审计日志方法
        """记录审计日志"""  # 方法文档字符串
        # 持久化到记忆系统
        try:
            ms = await get_memory_service()
            await ms.add_memory(
                user_id=log.user_id,
                content={
                    "type": "security_audit",
                    "log": log.to_dict()
                },
                memory_type="security_audit",
                layer="L3",
                scene=f"security_audit_{log.user_id}",
                rating=5,
                expire_days=30,
                source="system"
            )
        except Exception as e:
            logger.error(f"[SecurityManager] 审计日志保存失败: {e}")

        # 触发回调
        for callback in self._audit_callbacks:  # 遍历所有注册的回调
            try:  # 异常处理：确保一个回调失败不影响其他回调
                callback(log)  # 执行回调函数
            except Exception as e:  # 捕获回调异常
                logger.error(f"[SecurityManager] 审计回调执行失败: {e}")  # 记录错误

    async def _request_user_confirmation(  # 请求用户确认方法（异步）
        self,
        user_id: str,  # 用户ID
        tool_name: str,  # 工具名称
        params: dict,  # 参数
        reason: str,  # 原因
        risk_level: RiskLevel  # 风险等级
    ) -> bool:  # 返回是否确认
        """
        请求用户确认
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            params: 参数
            reason: 原因
            risk_level: 风险等级
        Returns:
            是否确认
        """  # 方法文档字符串
        # 如果有回调函数，使用它
        if self._confirmation_callback:  # 检查是否设置了确认回调
            try:  # 异常处理块
                future = self._confirmation_callback(user_id, tool_name, params, reason)  # 调用回调
                if asyncio.isfuture(future):  # 检查返回的是否是Future对象
                    return await future  # 异步等待Future结果
                return bool(future)  # 直接转换结果为布尔值
            except Exception as e:  # 捕获回调执行异常
                logger.error(f"[SecurityManager] 确认回调执行失败: {e}")  # 记录错误
                return False  # 回调失败默认拒绝

        # 默认实现：直接拒绝（安全默认）
        logger.warning(f"[SecurityManager] 无确认回调，默认拒绝操作: {tool_name}")  # 记录警告
        return False  # 没有回调时默认拒绝（安全原则）

    async def authorize_operation(  # 授权操作方法（完整流程）
        self,
        user_id: str,  # 用户ID
        tool_name: str,  # 工具名称
        params: dict | None = None,  # 工具参数
        request_context: dict | None = None  # 请求上下文
    ) -> AuthorizationResult:  # 返回授权结果
        """
        授权操作（完整流程）
        流程：
        1. 策略检查（白名单/黑名单）
        2. 风险评估
        3. 用户确认（如果需要）
        4. 记录决策
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            params: 工具参数
            request_context: 请求上下文
        Returns:
            授权结果
        """  # 方法文档字符串
        import uuid  # 导入uuid模块
        start_time = time.time()  # 记录开始时间
        params = params or {}  # 参数默认为空字典
        request_context = request_context or {}  # 上下文默认为空字典
        source = request_context.get("source", "user")  # 获取来源，默认为user

        log_id = str(uuid.uuid4())  # 生成审计日志ID

        # 1. 策略检查
        allowed, reason = await self.policy_center.check_tool_allowed(
            user_id, tool_name, source  # 检查工具是否被允许
        )

        if not allowed:  # 策略检查未通过
            duration = (time.time() - start_time) * 1000  # 计算耗时（毫秒）
            result = AuthorizationResult(  # 创建拒绝结果
                status=AuthorizationStatus.DENIED,
                denied=True,
                reason=reason,
                audit_log_id=log_id
            )

            # 记录审计日志
            await self._log_audit(SecurityAuditLog(
                log_id=log_id,
                user_id=user_id,
                tool_name=tool_name,
                params=params,
                context=request_context,
                decision="denied",
                reason=reason,
                risk_level=None,
                duration_ms=duration
            ))

            return result  # 返回拒绝结果

        # 2. 风险评估
        assessment = await self.safety_guard.assess_risk(
            user_id, tool_name, params, request_context  # 评估操作风险
        )

        # 如果直接阻止
        if assessment.level == RiskLevel.BLOCK:  # 风险等级为阻止
            duration = (time.time() - start_time) * 1000  # 计算耗时
            result = AuthorizationResult(  # 创建拒绝结果
                status=AuthorizationStatus.DENIED,
                denied=True,
                reason=assessment.reason,
                risk_level=assessment.level,
                audit_log_id=log_id
            )

            # 记录审计日志
            await self._log_audit(SecurityAuditLog(
                log_id=log_id,
                user_id=user_id,
                tool_name=tool_name,
                params=params,
                context=request_context,
                decision="denied",
                reason=assessment.reason,
                risk_level=assessment.level.value,
                duration_ms=duration
            ))

            return result  # 返回拒绝结果

        # 3. 确认处理
        if assessment.requires_confirmation or assessment.level in [RiskLevel.NOTICE, RiskLevel.CONFIRM]:  # 需要确认
            # 检查是否需要自动确认（基于用户历史）
            profile = await self.safety_guard.get_user_profile(user_id)  # 获取用户安全画像
            user_config = await self.policy_center.get_user_config(user_id)  # 获取用户策略配置

            confirm_count = profile.confirmed_operations.get(tool_name, 0)  # 获取该工具确认次数
            auto_threshold = user_config.auto_confirm_threshold  # 获取自动确认阈值

            if confirm_count >= auto_threshold and tool_name in profile.trusted_tools:  # 满足自动确认条件
                # 自动确认
                logger.info(f"[SecurityManager] 工具 {tool_name} 自动确认（已确认{confirm_count}次）")
                confirmed = True  # 自动确认通过
            else:  # 需要用户确认
                confirmed = await self._request_user_confirmation(
                    user_id, tool_name, params, assessment.reason, assessment.level
                )

            # 记录确认行为（用于学习）
            await self.safety_guard.record_confirmation(user_id, tool_name, confirmed)

            if not confirmed:  # 用户拒绝或未响应
                duration = (time.time() - start_time) * 1000  # 计算耗时
                result = AuthorizationResult(  # 创建拒绝结果
                    status=AuthorizationStatus.DENIED,
                    denied=True,
                    reason="用户拒绝确认",
                    risk_level=assessment.level,
                    audit_log_id=log_id
                )

                # 记录审计日志
                await self._log_audit(SecurityAuditLog(
                    log_id=log_id,
                    user_id=user_id,
                    tool_name=tool_name,
                    params=params,
                    context=request_context,
                    decision="rejected",
                    reason="用户拒绝确认",
                    risk_level=assessment.level.value,
                    duration_ms=duration
                ))

                return result  # 返回拒绝结果

            # 用户确认通过
            duration = (time.time() - start_time) * 1000  # 计算耗时
            result = AuthorizationResult(  # 创建允许结果
                status=AuthorizationStatus.ALLOWED,
                denied=False,
                reason=f"用户确认执行: {assessment.reason}",
                risk_level=assessment.level,
                audit_log_id=log_id
            )

            # 记录审计日志
            await self._log_audit(SecurityAuditLog(
                log_id=log_id,
                user_id=user_id,
                tool_name=tool_name,
                params=params,
                context=request_context,
                decision="confirmed",
                reason=assessment.reason,
                risk_level=assessment.level.value,
                duration_ms=duration
            ))

            return result  # 返回允许结果

        # 4. 直接允许（低风险）
        duration = (time.time() - start_time) * 1000  # 计算耗时
        result = AuthorizationResult(  # 创建允许结果
            status=AuthorizationStatus.ALLOWED,
            denied=False,
            reason=assessment.reason,
            risk_level=assessment.level,
            audit_log_id=log_id
        )

        # 记录审计日志
        await self._log_audit(SecurityAuditLog(
            log_id=log_id,
            user_id=user_id,
            tool_name=tool_name,
            params=params,
            context=request_context,
            decision="allowed",
            reason=assessment.reason,
            risk_level=assessment.level.value if assessment.level else None,
            duration_ms=duration
        ))

        return result  # 返回允许结果

    async def quick_check(  # 快速检查方法（不触发确认流程）
        self,
        user_id: str,  # 用户ID
        tool_name: str,  # 工具名称
        params: dict | None = None,  # 参数
        source: str = "user"  # 来源
    ) -> tuple[bool, str]:  # 返回(是否允许, 原因)
        """
        快速检查（不触发确认流程）
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            params: 参数
            source: 来源
        Returns:
            (allowed, reason)
        """  # 方法文档字符串
        # 1. 策略检查
        allowed, reason = await self.policy_center.check_tool_allowed(
            user_id, tool_name, source  # 检查工具策略
        )
        if not allowed:  # 策略不允许
            return False, reason  # 返回拒绝

        # 2. 快速风险评估
        assessment = await self.safety_guard.assess_risk(user_id, tool_name, params, {})

        if assessment.level == RiskLevel.BLOCK:  # 风险等级为阻止
            return False, assessment.reason  # 返回拒绝

        return True, assessment.reason  # 返回允许

    async def record_operation_result(  # 记录操作结果方法
        self,
        user_id: str,  # 用户ID
        tool_name: str,  # 工具名称
        params: dict,  # 参数
        success: bool,  # 是否成功
        error: str | None = None  # 错误信息
    ):  # 无返回值
        """
        记录操作结果（用于学习）
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            params: 参数
            success: 是否成功
            error: 错误信息
        """  # 方法文档字符串
        if not success and error:  # 如果执行失败且有错误信息
            # 记录事故
            await self.safety_guard.record_accident(user_id, tool_name, error)

    async def get_user_security_summary(self, user_id: str) -> dict[str, Any]:  # 获取用户安全摘要方法
        """
        获取用户安全摘要
        Args:
            user_id: 用户ID
        Returns:
            安全摘要
        """  # 方法文档字符串
        profile_stats = await self.safety_guard.get_profile_stats(user_id)  # 获取安全画像统计
        policy_summary = await self.policy_center.get_user_config_summary(user_id)  # 获取策略配置摘要

        return {  # 返回综合安全摘要
            "user_id": user_id,
            "safety_profile": profile_stats,
            "policy_config": policy_summary,
            "risk_assessment": {
                "trusted_tools_count": profile_stats.get("trusted_tools_count", 0),  # 信任工具数
                "blocked_tools_count": profile_stats.get("blocked_tools_count", 0) + policy_summary.get("blocked_tools_count", 0),  # 阻止工具数（画像+策略）
                "accident_count": profile_stats.get("accident_count", 0),  # 事故次数
                "risk_threshold_adjustment": profile_stats.get("risk_threshold_adjustment", 0.0)  # 风险阈值调整
            }
        }

    async def reset_user_security(self, user_id: str) -> bool:  # 重置用户安全设置方法
        """
        重置用户安全设置
        Args:
            user_id: 用户ID
        Returns:
            是否成功
        """  # 方法文档字符串
        try:  # 异常处理块
            await self.safety_guard.reset_user_profile(user_id)  # 重置安全画像
            await self.policy_center.reset_user_config(user_id)  # 重置策略配置
            logger.info(f"[SecurityManager] 用户 {user_id} 的安全设置已重置")  # 记录日志
            return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[SecurityManager] 重置用户安全设置失败: {e}")  # 记录错误
            return False  # 返回失败


# 全局实例
security_manager = MultiTenantSecurityManager()  # 创建模块级单例实例，供全系统使用


# 便捷函数
async def authorize(  # 授权便捷函数
    user_id: str,  # 用户ID
    tool_name: str,  # 工具名称
    params: dict = None,  # 参数
    context: dict = None  # 上下文
) -> AuthorizationResult:  # 返回授权结果
    """便捷函数：授权操作"""  # 函数文档字符串
    return await security_manager.authorize_operation(user_id, tool_name, params, context)  # 调用管理器方法


async def quick_authorize(  # 快速授权便捷函数
    user_id: str,  # 用户ID
    tool_name: str,  # 工具名称
    params: dict = None,  # 参数
    source: str = "user"  # 来源
) -> tuple[bool, str]:  # 返回(是否允许, 原因)
    """便捷函数：快速授权检查"""  # 函数文档字符串
    return await security_manager.quick_check(user_id, tool_name, params, source)  # 调用管理器方法


async def get_user_security_status(user_id: str) -> dict[str, Any]:  # 获取用户安全状态便捷函数
    """便捷函数：获取用户安全状态"""  # 函数文档字符串
    return await security_manager.get_user_security_summary(user_id)  # 调用管理器方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"增强安全层"，实现多租户安全管理。在基础安全守卫
# (safety_guard.py)之上提供统一的授权流程、用户级安全隔离、完整审计追踪功能。
#
# 【架构设计】
# - MultiTenantSecurityManager: 核心安全管理器，单例模式，整合SafetyGuard和PolicyCenter
# - ConfirmationManager: 确认请求管理，支持异步确认流程和超时清理
# - AuthorizationResult/SecurityAuditLog: 数据类封装授权结果和审计日志
# - 4步授权流程: 策略检查 → 风险评估 → 用户确认 → 记录决策
#
# 【关联文件】
# - core/safety_guard.py     : SafetyGuard实例，提供风险评估和用户画像
# - core/policy.py           : PolicyCenter实例，提供策略检查
# - core/memory.py           : 记忆管理器，用于持久化审计日志到L3层
# - core/logger.py           : 日志记录器，记录安全事件
# - core/agent_loop.py       : 调用方，在工具执行前调用authorize_operation()
# - core/tool_executor.py    : 调用方，执行后调用record_operation_result()
#
# 【核心功能效果】
# 1. 统一授权流程: 4步标准化流程确保所有操作经过完整安全检查
# 2. 多租户隔离: 每个用户独立的安全画像和策略配置，数据互不影响
# 3. 动态风险响应: 基于用户历史自动确认（信任工具+确认次数达标）
# 4. 完整审计追踪: 所有授权决策记录到L3记忆，30天保留期
# 5. 异步确认支持: 支持UI交互式确认，Future异步等待用户响应
# 6. 安全学习: 操作结果反馈到SafetyGuard，持续优化风险模型
#
# 【数据流向】
# 授权流程: authorize_operation() → 策略检查 → 风险评估 → [用户确认] → 记录审计日志
# 确认流程: create_request() → _request_user_confirmation() → confirm() → _cleanup_after_delay()
# 审计记录: _log_audit() → memory_manager.add(L3层) + 触发_audit_callbacks
# 学习反馈: record_operation_result() → safety_guard.record_accident()
#
# 【使用场景】
# 场景1: 工具执行前 → authorize(user_id, tool, params) → 返回ALLOWED/DENIED
# 场景2: 快速检查 → quick_authorize() → 返回(bool, reason)，不触发确认
# 场景3: 需要确认 → 创建token → UI回调 → confirm(token, True/False) → 完成授权
# 场景4: 执行失败 → record_operation_result(success=False, error=...) → 记录事故
# 场景5: 安全总览 → get_user_security_status() → 返回信任/阻止工具数、事故数
# =============================================================================
