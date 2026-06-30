#!/usr/bin/env python3
"""
工具执行审计中间件 - 云端+本地双版本工具管控架构

功能：
1. 本地模式：直接放行，仅记录日志
2. 云端模式：校验执行权限，记录审计日志
3. 混合模式：根据策略决定是否放行

版本历史:
- 2026-03-09: 初始版本，支持云端+本地双版本管控
"""
import time
from enum import Enum

# 导入核心组件
from core.config import config
from core.logger import logger
from core.tool.tool_manager import tool_manager


class ToolExecutionError(Exception):
    """工具执行错误"""
    pass


class AuditLevel(Enum):
    """审计级别"""
    NONE = "none"           # 不审计
    BASIC = "basic"         # 基础审计（仅记录工具ID）
    FULL = "full"           # 完整审计（记录参数和结果）
    STRICT = "strict"       # 严格审计（包含用户上下文）


class ToolAuditMiddleware:
    """
    工具执行审计中间件

    根据部署模式执行不同的审计策略：
    - local: 仅记录日志，不拦截
    - cloud: 校验权限，记录完整审计日志
    - hybrid: 用户自定义工具放行，系统工具受限

    使用示例:
        middleware = ToolAuditMiddleware()

        # 执行前检查
        allowed = await middleware.before_execute("file_read", "user_123", {"path": "/tmp/test.txt"})
        if not allowed:
            raise ToolExecutionError("执行被拒绝")

        # 执行工具...
        result = tool.run(**params)

        # 执行后记录
        await middleware.after_execute("file_read", "user_123", params, result)
    """

    def __init__(self, audit_level: AuditLevel = None):
        """
        初始化审计中间件

        Args:
            audit_level: 审计级别，为None时根据部署模式自动选择
        """
        self.deploy_mode = config.get_deploy_mode()
        self.audit_level = audit_level or self._get_default_audit_level()

        # 审计日志存储（实际生产环境应使用数据库或日志服务）
        self._audit_logs: list = []
        self._max_logs = 10000  # 最大审计日志数量

        logger.info(f"[ToolAuditMiddleware] 初始化完成，部署模式: {self.deploy_mode}, 审计级别: {self.audit_level.value}")

    def _get_default_audit_level(self) -> AuditLevel:
        """
        根据部署模式获取默认审计级别

        Returns:
            AuditLevel: 默认审计级别
        """
        if self.deploy_mode == "local":
            return AuditLevel.BASIC
        elif self.deploy_mode == "cloud" or self.deploy_mode == "hybrid":
            return AuditLevel.FULL
        else:
            return AuditLevel.BASIC

    async def before_execute(self, tool_id: str, user_id: str, params: dict) -> bool:
        """
        工具执行前检查

        Args:
            tool_id: 工具ID
            user_id: 用户ID
            params: 执行参数

        Returns:
            bool: 是否允许执行

        Raises:
            ToolExecutionError: 当执行被禁止时抛出
        """
        time.time()

        # 本地模式：直接放行，仅记录日志
        if self.deploy_mode == "local":
            logger.info(f"[本地执行] 工具: {tool_id}, 用户: {user_id}")
            self._log_audit("before_execute", tool_id, user_id, params, None, "local_allowed")
            return True

        # 云端模式：校验执行权限
        if self.deploy_mode == "cloud":
            return await self._check_cloud_permission(tool_id, user_id, params)

        # 混合模式：用户自定义工具可执行
        if self.deploy_mode == "hybrid":
            return await self._check_hybrid_permission(tool_id, user_id, params)

        # 未知模式：保守策略，拒绝执行
        logger.error(f"[ToolAuditMiddleware] 未知的部署模式: {self.deploy_mode}")
        raise ToolExecutionError(f"未知的部署模式: {self.deploy_mode}")

    async def _check_cloud_permission(self, tool_id: str, user_id: str, params: dict) -> bool:
        """
        云端模式权限检查

        Args:
            tool_id: 工具ID
            user_id: 用户ID
            params: 执行参数

        Returns:
            bool: 是否允许执行

        Raises:
            ToolExecutionError: 当执行被禁止时抛出
        """
        # 获取工具信息（含权限计算）
        tool_info = tool_manager.get_tool_info(tool_id, user_id)

        if not tool_info:
            self._log_audit("permission_denied", tool_id, user_id, params, None, "tool_not_found")
            raise ToolExecutionError(f"工具不存在: {tool_id}")

        # 检查是否可执行
        if not tool_info.get("executable", False):
            restriction = tool_info.get("exec_restriction", "未知原因")
            self._log_audit("permission_denied", tool_id, user_id, params, None, restriction)
            raise ToolExecutionError(f"无法执行: {restriction}")

        # 记录审计日志
        self._log_audit("before_execute", tool_id, user_id, params, None, "cloud_allowed")

        logger.info(f"[云端执行] 工具: {tool_id}, 用户: {user_id}, 权限校验通过")
        return True

    async def _check_hybrid_permission(self, tool_id: str, user_id: str, params: dict) -> bool:
        """
        混合模式权限检查

        Args:
            tool_id: 工具ID
            user_id: 用户ID
            params: 执行参数

        Returns:
            bool: 是否允许执行

        Raises:
            ToolExecutionError: 当执行被禁止时抛出
        """
        tool_info = tool_manager.get_tool_info(tool_id, user_id)

        if not tool_info:
            self._log_audit("permission_denied", tool_id, user_id, params, None, "tool_not_found")
            raise ToolExecutionError(f"工具不存在: {tool_id}")

        owner = tool_info.get("owner", "system")

        # 用户自定义工具始终可执行
        if owner == "custom":
            self._log_audit("before_execute", tool_id, user_id, params, None, "hybrid_custom_allowed")
            return True

        # 检查是否可执行
        if not tool_info.get("executable", False):
            restriction = tool_info.get("exec_restriction", "未知原因")
            self._log_audit("permission_denied", tool_id, user_id, params, None, restriction)
            raise ToolExecutionError(f"无法执行: {restriction}")

        self._log_audit("before_execute", tool_id, user_id, params, None, "hybrid_allowed")
        return True

    async def after_execute(self, tool_id: str, user_id: str, params: dict,
                           result: dict, duration: float = None):
        """
        工具执行后记录

        Args:
            tool_id: 工具ID
            user_id: 用户ID
            params: 执行参数
            result: 执行结果
            duration: 执行耗时（秒）
        """
        success = result.get("success", False) if isinstance(result, dict) else False
        result.get("error_code") if isinstance(result, dict) else None

        # 根据审计级别决定记录内容
        if self.audit_level == AuditLevel.NONE:
            return

        # 记录审计日志
        status = "success" if success else "failed"
        self._log_audit("after_execute", tool_id, user_id, params, result, status, duration)

        # 本地模式简化日志
        if self.deploy_mode == "local":
            logger.info(f"[本地执行完成] 工具: {tool_id}, 用户: {user_id}, 结果: {status}")
        else:
            logger.info(f"[云端执行完成] 工具: {tool_id}, 用户: {user_id}, 结果: {status}, 耗时: {duration:.3f}s" if duration else f"[云端执行完成] 工具: {tool_id}, 用户: {user_id}, 结果: {status}")

    def _log_audit(self, event_type: str, tool_id: str, user_id: str,
                   params: dict, result: dict, status: str, duration: float = None):
        """
        记录审计日志

        Args:
            event_type: 事件类型
            tool_id: 工具ID
            user_id: 用户ID
            params: 执行参数
            result: 执行结果
            status: 状态
            duration: 执行耗时
        """
        # 脱敏敏感参数
        sanitized_params = self._sanitize_params(params)

        log_entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "tool_id": tool_id,
            "user_id": user_id,
            "deploy_mode": self.deploy_mode,
            "audit_level": self.audit_level.value,
            "status": status,
            "duration": duration
        }

        # 根据审计级别添加详细信息
        if self.audit_level in [AuditLevel.FULL, AuditLevel.STRICT]:
            log_entry["params"] = sanitized_params
            if result:
                # 简化结果，避免日志过大
                log_entry["result_summary"] = {
                    "success": result.get("success") if isinstance(result, dict) else None,
                    "error_code": result.get("error_code") if isinstance(result, dict) else None
                }

        if self.audit_level == AuditLevel.STRICT:
            # 严格审计可以添加更多上下文信息
            log_entry["source_ip"] = None  # 可由调用方提供
            log_entry["session_id"] = None  # 可由调用方提供

        # 添加到审计日志列表
        self._audit_logs.append(log_entry)

        # 限制日志数量
        if len(self._audit_logs) > self._max_logs:
            self._audit_logs = self._audit_logs[-self._max_logs:]

        # 同时输出到系统日志
        logger.debug(f"[Audit] {event_type}: tool={tool_id}, user={user_id}, status={status}")

    def _sanitize_params(self, params: dict) -> dict:
        """
        脱敏敏感参数

        Args:
            params: 原始参数

        Returns:
            dict: 脱敏后的参数
        """
        if not isinstance(params, dict):
            return params

        # 敏感关键词列表
        sensitive_keys = [
            'password', 'passwd', 'pwd', 'token', 'secret', 'key', 'api_key',
            'auth', 'authorization', 'credential', 'credentials', 'private',
            'private_key', 'access_token', 'refresh_token', 'session',
            'cookie', 'csrf', 'xsrf', 'nonce', 'signature'
        ]

        sanitized = {}
        for key, value in params.items():
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_keys):
                if isinstance(value, str):
                    sanitized[key] = f"***REDACTED(len={len(value)})***"
                else:
                    sanitized[key] = "***REDACTED***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_params(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_params(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized

    def get_audit_logs(self, limit: int = 100,
                       tool_id: str = None,
                       user_id: str = None,
                       status: str = None) -> list:
        """
        获取审计日志

        Args:
            limit: 返回条数限制
            tool_id: 过滤特定工具
            user_id: 过滤特定用户
            status: 过滤特定状态

        Returns:
            list: 审计日志列表
        """
        logs = self._audit_logs

        # 应用过滤器
        if tool_id:
            logs = [log for log in logs if log.get("tool_id") == tool_id]
        if user_id:
            logs = [log for log in logs if log.get("user_id") == user_id]
        if status:
            logs = [log for log in logs if log.get("status") == status]

        # 返回最近的日志
        return logs[-limit:]

    def clear_audit_logs(self):
        """清空审计日志"""
        self._audit_logs.clear()
        logger.info("[ToolAuditMiddleware] 审计日志已清空")

    def get_statistics(self) -> dict:
        """
        获取审计统计信息

        Returns:
            dict: 统计信息
        """
        total = len(self._audit_logs)

        if total == 0:
            return {
                "total_logs": 0,
                "deploy_mode": self.deploy_mode,
                "audit_level": self.audit_level.value
            }

        # 统计各种状态的数量
        status_counts = {}
        tool_counts = {}
        user_counts = {}

        for log in self._audit_logs:
            status = log.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

            tool = log.get("tool_id", "unknown")
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

            user = log.get("user_id", "unknown")
            user_counts[user] = user_counts.get(user, 0) + 1

        return {
            "total_logs": total,
            "deploy_mode": self.deploy_mode,
            "audit_level": self.audit_level.value,
            "status_distribution": status_counts,
            "most_used_tools": sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10],
            "active_users": sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        }


# 全局中间件实例（单例）
_tool_audit_middleware: ToolAuditMiddleware | None = None


def get_tool_audit_middleware() -> ToolAuditMiddleware:
    """
    获取全局审计中间件实例

    Returns:
        ToolAuditMiddleware: 审计中间件实例
    """
    global _tool_audit_middleware
    if _tool_audit_middleware is None:
        _tool_audit_middleware = ToolAuditMiddleware()
    return _tool_audit_middleware


# 便捷函数
async def check_tool_execution(tool_id: str, user_id: str, params: dict) -> bool:
    """
    检查工具执行权限（便捷函数）

    Args:
        tool_id: 工具ID
        user_id: 用户ID
        params: 执行参数

    Returns:
        bool: 是否允许执行
    """
    middleware = get_tool_audit_middleware()
    return await middleware.before_execute(tool_id, user_id, params)


async def record_tool_execution(tool_id: str, user_id: str, params: dict,
                                result: dict, duration: float = None):
    """
    记录工具执行（便捷函数）

    Args:
        tool_id: 工具ID
        user_id: 用户ID
        params: 执行参数
        result: 执行结果
        duration: 执行耗时
    """
    middleware = get_tool_audit_middleware()
    await middleware.after_execute(tool_id, user_id, params, result, duration)
