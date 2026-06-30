#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
import json

# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
安全策略中心 V5.1 - 多用户策略管理  # 模块功能概述：安全策略管理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  # 分隔线
【核心功能】  # 功能列表
1. 用户级策略配置（UserPolicyConfig）  # 功能1
2. 工具风险分级  # 功能2
3. 用户白名单/黑名单管理  # 功能3
4. 自定义风险等级  # 功能4

【架构设计】  # 架构设计
  ┌─────────────────────────────────────────┐  # 图示开始
  │           PolicyCenter                  │  # 策略中心
  │  ┌─────────────────────────────────┐    │  # 用户配置
  │  │   UserPolicyConfig (per user)   │    │  # 每个用户的配置
  │  │   · allowed_tools               │    │  # 允许的工具
  │  │   · blocked_tools               │    │  # 阻止的工具
  │  │   · custom_risk_levels          │    │  # 自定义风险等级
  │  │   · require_confirmation_for    │    │  # 需要确认的操作
  │  └─────────────────────────────────┘    │  # 配置结束
  └─────────────────────────────────────────┘  # 图示结束

【2026-02-26 重构】  # 版本历史
- 新增多用户支持  # 变更1
- 用户级工具白名单  # 变更2
- 自定义风险等级  # 变更3
"""  # 文档字符串结束

import os  # 导入操作系统模块
import re  # 导入正则表达式模块
from dataclasses import dataclass, field  # 从dataclasses导入数据类装饰器
from datetime import datetime  # 从datetime导入日期时间类
from typing import Any  # 从typing导入类型注解

from core.config import config  # 导入配置模块
from core.logger import logger  # 导入日志记录器

from ..safety.risk_level import RiskLevel  # 导入风险等级枚举

# 系统保护路径
PROTECTED_PATHS = [  # 模块级常量：受保护路径列表
    "C:\\Windows",  # Windows系统目录
    "C:\\Program Files",  # 程序文件目录
    "C:\\Program Files (x86)",  # 32位程序目录
    os.path.expanduser("~"),  # 用户目录（可配置允许）
]

# 系统保护进程名
PROTECTED_PROCESSES = [  # 模块级常量：受保护进程列表
    "explorer.exe", "svchost.exe", "winlogon.exe",
    "csrss.exe", "services.exe", "systemd", "init",
    "kernel", "system", "registry"
]


def is_protected_path(path: str) -> bool:  # 判断路径是否属于受保护目录
    """判断路径是否属于受保护的目录"""  # 函数文档字符串
    if not path:  # 如果路径为空
        return False  # 返回False
    # 路径穿越检查
    normalized = os.path.normpath(path)  # 规范化路径
    # 检查是否尝试访问上层目录
    if ".." in normalized or normalized.startswith("\\\\"):  # 路径穿越检查
        return True  # 是受保护路径
    # 检查是否在保护路径内
    return any(normalized.lower().startswith(protected.lower()) for protected in PROTECTED_PATHS)  # 不是受保护路径


def is_protected_process(proc_name: str) -> bool:  # 判断进程名是否受保护
    """判断进程名是否受保护"""  # 函数文档字符串
    if not proc_name:  # 如果进程名为空
        return False  # 返回False
    # 检查PID<100的系统进程（通过名称判断）
    lower_name = proc_name.lower()  # 转小写
    for protected in PROTECTED_PROCESSES:  # 遍历保护进程
        if lower_name == protected.lower() or lower_name.endswith(protected.lower()):  # 如果匹配
            return True  # 是受保护进程
    return False  # 不是受保护进程


def get_tool_risk(tool_id: str) -> RiskLevel:  # 从配置获取工具风险等级
    """从配置获取工具风险等级，默认返回 HIGH"""  # 函数文档字符串
    try:  # 异常处理
        risk_map = config.get_risk_map()  # 从配置获取风险映射
    except Exception:  # 捕获异常
        risk_map = {}  # 使用空字典
    risk_name = risk_map.get(tool_id, risk_map.get("default", "HIGH"))  # 获取风险名称，默认HIGH
    return getattr(RiskLevel, risk_name.upper(), RiskLevel.HIGH)  # 返回风险等级枚举


def is_high_risk(tool_id: str) -> bool:  # 检查是否高风险工具
    """检查是否高风险工具"""  # 函数文档字符串
    return get_tool_risk(tool_id) == RiskLevel.HIGH  # 返回是否为HIGH


def is_medium_risk(tool_id: str) -> bool:  # 检查是否中风险工具
    """检查是否中风险工具"""  # 函数文档字符串
    return get_tool_risk(tool_id) == RiskLevel.MEDIUM  # 返回是否为MEDIUM


def estimate_task_risk(task_intent: dict) -> RiskLevel:  # 根据任务描述估算风险等级
    """
    根据任务描述估算风险等级（用于 auto_loop 动态评估）
    使用正则边界匹配，避免误判
    """  # 函数文档字符串
    raw = task_intent.get("raw", "").lower()  # 获取原始指令并转小写
    try:  # 异常处理
        risk_keywords = config.get("risk_keywords", {})  # 从配置获取风险关键词
    except Exception:  # 捕获异常
        risk_keywords = {}  # 使用空字典

    for level, keywords in risk_keywords.items():  # 遍历风险等级和关键词
        for kw in keywords:  # 遍历关键词
            # 如果关键词包含空格，视为短语，直接使用转义字符串
            pattern = re.escape(kw) if ' ' in kw else r'\b' + re.escape(kw) + r'\b'  # 转义整个短语或添加单词边界
            if re.search(pattern, raw, re.IGNORECASE):  # 如果匹配
                return getattr(RiskLevel, level.upper(), RiskLevel.MEDIUM)  # 返回对应风险等级
    return RiskLevel.MEDIUM  # 默认中风险


@dataclass  # 数据类装饰器
class UserPolicyConfig:  # 用户策略配置数据类
    """用户策略配置"""  # 类文档字符串
    user_id: str  # 用户ID
    allowed_tools: set[str] = field(default_factory=set)  # 允许的工具集合
    blocked_tools: set[str] = field(default_factory=set)  # 阻止的工具集合
    custom_risk_levels: dict[str, RiskLevel] = field(default_factory=dict)  # 自定义风险等级字典
    require_confirmation_for: set[str] = field(default_factory=set)  # 需要确认的操作集合
    auto_confirm_threshold: int = 3  # 自动确认阈值（确认N次后）
    created_at: datetime = field(default_factory=datetime.now)  # 创建时间
    updated_at: datetime = field(default_factory=datetime.now)  # 更新时间

    def to_dict(self) -> dict[str, Any]:  # 转换为字典
        """转换为字典（用于序列化）"""  # 方法文档字符串
        return {  # 返回字典
            "user_id": self.user_id,  # 用户ID
            "allowed_tools": list(self.allowed_tools),  # 允许的工具列表
            "blocked_tools": list(self.blocked_tools),  # 阻止的工具列表
            "custom_risk_levels": {k: v.name for k, v in self.custom_risk_levels.items()},  # 风险等级名称
            "require_confirmation_for": list(self.require_confirmation_for),  # 需要确认的操作列表
            "auto_confirm_threshold": self.auto_confirm_threshold,  # 自动确认阈值
            "created_at": self.created_at.isoformat(),  # 创建时间（ISO格式）
            "updated_at": self.updated_at.isoformat()  # 更新时间（ISO格式）
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict[str, Any]) -> "UserPolicyConfig":  # 从字典创建
        """从字典创建"""  # 方法文档字符串
        custom_risk = {}  # 自定义风险字典
        for k, v in data.get("custom_risk_levels", {}).items():  # 遍历风险等级
            try:  # 异常处理
                custom_risk[k] = RiskLevel[v.upper()]  # 转换枚举
            except Exception:  # 转换失败
                custom_risk[k] = RiskLevel.MEDIUM  # 默认中风险

        return cls(  # 创建并返回实例
            user_id=data.get("user_id", ""),  # 用户ID
            allowed_tools=set(data.get("allowed_tools", [])),  # 允许的工具
            blocked_tools=set(data.get("blocked_tools", [])),  # 阻止的工具
            custom_risk_levels=custom_risk,  # 自定义风险等级
            require_confirmation_for=set(data.get("require_confirmation_for", [])),  # 需要确认的操作
            auto_confirm_threshold=data.get("auto_confirm_threshold", 3),  # 自动确认阈值
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),  # 创建时间
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat()))  # 更新时间
        )


class DefaultPolicy:  # 默认策略类
    """默认策略（非用户特定）"""  # 类文档字符串

    # 默认阻止的工具（全局）
    GLOBALLY_BLOCKED = {  # 类级常量：全局阻止的工具
        "credential_dump", "keylogger", "rootkit",
        "system_corrupt", "data_wipe", "ransomware"
    }

    # 默认需要确认的高危操作
    HIGH_RISK_OPERATIONS = {  # 类级常量：高危操作
        "format", "delete_system", "registry_delete",
        "driver_uninstall", "firewall_disable"
    }

    def check_tool(self, tool_id: str, source: str) -> tuple[bool, str]:  # 检查工具
        """
        检查工具是否允许执行（默认策略）

        Args:
            tool_id: 工具ID
            source: 来源

        Returns:
            (allowed, reason)
        """  # 方法文档字符串
        # 检查全局阻止列表
        if tool_id in self.GLOBALLY_BLOCKED:  # 如果在全局阻止列表
            return False, f"工具 {tool_id} 在全局阻止列表中"  # 返回不允许

        # 检查系统保护路径/进程
        if any(op in tool_id.lower() for op in self.HIGH_RISK_OPERATIONS):  # 如果包含高危操作
            return True, "高危操作，需要额外确认"  # 返回允许但需确认

        return True, "通过默认策略检查"  # 返回允许


class PolicyCenter:  # 策略中心类（多用户版）
    """
    策略中心（多用户版）

    【核心功能】
    - 用户策略配置管理
    - 工具访问控制
    - 自定义风险等级
    """  # 类文档字符串

    # 系统保留工具（不能被用户覆盖）
    SYSTEM_RESERVED_TOOLS = {  # 类级常量：系统保留工具
        "auth", "login", "logout", "security_check",
        "policy_update", "system_monitor"
    }

    def __init__(self):  # 初始化
        self._user_configs: dict[str, UserPolicyConfig] = {}  # 用户配置字典
        self._default_policy = DefaultPolicy()  # 默认策略实例

        logger.info("[PolicyCenter] 策略中心初始化完成")  # 记录日志

    def _create_default_config(self, user_id: str) -> UserPolicyConfig:  # 创建默认用户配置
        """创建默认用户配置"""  # 方法文档字符串
        return UserPolicyConfig(  # 创建配置
            user_id=user_id,
            allowed_tools=set(),  # 空表示允许所有（除了blocked）
            blocked_tools=set(),
            custom_risk_levels={},
            require_confirmation_for=set(),
            auto_confirm_threshold=3
        )

    async def _load_or_create_config(self, user_id: str) -> UserPolicyConfig:  # 加载或创建配置
        """加载或创建用户配置"""  # 方法文档字符串
        # 尝试从记忆恢复
        try:  # 异常处理
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()

            stored = await memory_service.query_memories(
                user_id=user_id,
                layer="L3",
                mem_type="policy_config",
                limit=1,
            )

            if stored and len(stored) > 0:  # 如果有记录
                content = stored[0].get("content", {})  # 获取内容
                if isinstance(content, dict) and "config" in content:  # 如果包含配置
                    logger.debug(f"[PolicyCenter] 从记忆恢复用户 {user_id} 的策略配置")  # 记录调试
                    return UserPolicyConfig.from_dict(content["config"])  # 从字典创建
        except Exception as e:  # 捕获异常
            logger.warning(f"[PolicyCenter] 从记忆恢复配置失败: {e}")  # 记录警告

        return self._create_default_config(user_id)  # 创建默认配置

    async def _persist_config(self, user_id: str, config: UserPolicyConfig):  # 持久化用户配置
        """持久化用户配置"""  # 方法文档字符串
        try:  # 异常处理
            from core.memory.memory_schema import MemoryMetadata
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()

            config.updated_at = datetime.now()  # 更新时间
            content = {
                "type": "policy_config",
                "config": config.to_dict()
            }
            content_json = json.dumps(content, ensure_ascii=False)
            metadata = MemoryMetadata(
                user_id=user_id,
                source="checkpoint",
                content_type="json",
                payload_summary=f"策略配置: {user_id}",
                raw_payload=content_json,
            )

            await memory_service.save_memory(
                user_id=user_id,
                layer="L3",
                mem_type="policy_config",
                content=content_json,
                metadata=metadata,
                scene=f"policy_config_{user_id}",
                rating=8,
                expire_days=365,
            )
        except Exception as e:  # 捕获异常
            logger.error(f"[PolicyCenter] 保存策略配置失败: {e}")  # 记录错误

    async def get_user_config(self, user_id: str) -> UserPolicyConfig:  # 获取用户策略配置
        """
        获取用户策略配置

        Args:
            user_id: 用户ID

        Returns:
            用户策略配置
        """  # 方法文档字符串
        if user_id not in self._user_configs:  # 如果缓存中没有
            self._user_configs[user_id] = await self._load_or_create_config(user_id)  # 加载或创建
        return self._user_configs[user_id]  # 返回配置

    async def check_tool_allowed(  # 检查工具是否允许使用
        self,
        user_id: str,  # 用户ID
        tool_name: str,  # 工具名称
        source: str = "user",  # 来源
        auto_loop_config: dict = None
    ) -> tuple[bool, str]:  # 返回是否允许及原因
        """
        检查工具是否允许使用（用户级）

        检查流程：
        1. 系统保留工具检查
        2. 用户阻止列表
        3. 用户允许列表
        4. 默认策略
        5. 自动任务风险过滤

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            source: 来源 'user' / 'auto_loop' / 'reflection' / 'test' / 'internal'
            auto_loop_config: auto_loop的配置

        Returns:
            (allowed: bool, reason: str)
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取用户配置

        # 1. 系统保留工具（不能被用户阻止）
        if tool_name in self.SYSTEM_RESERVED_TOOLS:  # 如果是系统保留工具
            return True, "系统保留工具，跳过用户策略检查"  # 允许

        # 2. 检查用户阻止列表
        if tool_name in config.blocked_tools:  # 如果在阻止列表
            return False, f"工具 {tool_name} 在用户的阻止列表中"  # 不允许

        # 3. 检查用户允许列表（如果配置了）
        if config.allowed_tools and tool_name not in config.allowed_tools:  # 如果配置了允许列表但不在其中
            return False, f"工具 {tool_name} 不在用户的允许列表中"  # 不允许

        # 4. 应用默认策略
        allowed, reason = self._default_policy.check_tool(tool_name, source)  # 检查默认策略
        if not allowed:  # 如果不允许
            return False, reason  # 返回原因

        # 5. 自动任务风险过滤
        if source == "auto_loop" and auto_loop_config:  # 如果是自动任务
            risk = get_tool_risk(tool_name)  # 获取风险等级
            blocked_risks = auto_loop_config.get("blocked_risks", ["HIGH", "MEDIUM"])  # 获取阻止的风险等级
            risk_names = {  # 风险等级名称映射
                RiskLevel.LOW: "LOW",
                RiskLevel.MEDIUM: "MEDIUM",
                RiskLevel.HIGH: "HIGH",
                RiskLevel.CRITICAL: "CRITICAL"
            }
            if risk_names.get(risk, "HIGH") in blocked_risks:  # 如果在阻止列表
                return False, f"自动任务禁止执行风险等级为 {risk_names[risk]} 的工具"  # 不允许

        # 6. 检查是否需要用户确认
        if tool_name in config.require_confirmation_for:  # 如果需要确认
            return True, "工具需要用户确认"  # 允许但需确认

        return True, "允许执行"  # 允许执行

    async def set_user_risk_level(self, user_id: str, tool_name: str, level: RiskLevel):  # 设置用户自定义风险等级
        """
        用户自定义工具风险等级

        Args:
            user_id: 用户ID
            tool_name: 工具名称
            level: 风险等级
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.custom_risk_levels[tool_name] = level  # 设置风险等级
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 设置工具 {tool_name} 风险等级为 {level.name}")  # 记录日志

    async def get_user_risk_level(self, user_id: str, tool_name: str) -> RiskLevel:  # 获取用户自定义风险等级
        """
        获取用户自定义的风险等级

        Args:
            user_id: 用户ID
            tool_name: 工具名称

        Returns:
            风险等级（未设置则返回默认）
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        if tool_name in config.custom_risk_levels:  # 如果设置了
            return config.custom_risk_levels[tool_name]  # 返回自定义等级
        return get_tool_risk(tool_name)  # 返回默认等级

    async def add_user_allowed_tool(self, user_id: str, tool_name: str):  # 添加用户允许的工具
        """
        添加用户允许的工具

        Args:
            user_id: 用户ID
            tool_name: 工具名称
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.allowed_tools.add(tool_name)  # 添加到允许列表
        if tool_name in config.blocked_tools:  # 如果同时在阻止列表
            config.blocked_tools.remove(tool_name)  # 从阻止列表移除
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 添加允许工具: {tool_name}")  # 记录日志

    async def remove_user_allowed_tool(self, user_id: str, tool_name: str):  # 移除用户允许的工具
        """
        移除用户允许的工具

        Args:
            user_id: 用户ID
            tool_name: 工具名称
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.allowed_tools.discard(tool_name)  # 从允许列表移除
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 移除允许工具: {tool_name}")  # 记录日志

    async def add_user_blocked_tool(self, user_id: str, tool_name: str):  # 添加用户阻止的工具
        """
        添加用户阻止的工具

        Args:
            user_id: 用户ID
            tool_name: 工具名称
        """  # 方法文档字符串
        # 不能阻止系统保留工具
        if tool_name in self.SYSTEM_RESERVED_TOOLS:  # 如果是系统保留工具
            logger.warning(f"[PolicyCenter] 不能阻止系统保留工具: {tool_name}")  # 记录警告
            return False  # 返回失败

        config = await self.get_user_config(user_id)  # 获取配置
        config.blocked_tools.add(tool_name)  # 添加到阻止列表
        if tool_name in config.allowed_tools:  # 如果同时在允许列表
            config.allowed_tools.discard(tool_name)  # 从允许列表移除
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 添加阻止工具: {tool_name}")  # 记录日志
        return True  # 返回成功

    async def remove_user_blocked_tool(self, user_id: str, tool_name: str):  # 移除用户阻止的工具
        """
        移除用户阻止的工具

        Args:
            user_id: 用户ID
            tool_name: 工具名称
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.blocked_tools.discard(tool_name)  # 从阻止列表移除
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 移除阻止工具: {tool_name}")  # 记录日志

    async def add_require_confirmation(self, user_id: str, tool_name: str):  # 添加需要确认的工具
        """
        添加需要确认的工具

        Args:
            user_id: 用户ID
            tool_name: 工具名称
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.require_confirmation_for.add(tool_name)  # 添加到需要确认列表
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 添加需要确认工具: {tool_name}")  # 记录日志

    async def remove_require_confirmation(self, user_id: str, tool_name: str):  # 移除需要确认的工具
        """
        移除需要确认的工具

        Args:
            user_id: 用户ID
            tool_name: 工具名称
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.require_confirmation_for.discard(tool_name)  # 从需要确认列表移除
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 移除需要确认工具: {tool_name}")  # 记录日志

    async def set_auto_confirm_threshold(self, user_id: str, threshold: int):  # 设置自动确认阈值
        """
        设置自动确认阈值

        Args:
            user_id: 用户ID
            threshold: 阈值（确认N次后自动信任）
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        config.auto_confirm_threshold = max(1, min(10, threshold))  # 限制在1-10之间
        config.updated_at = datetime.now()  # 更新时间

        await self._persist_config(user_id, config)  # 持久化
        logger.info(f"[PolicyCenter] 用户 {user_id} 设置自动确认阈值为: {config.auto_confirm_threshold}")  # 记录日志

    async def reset_user_config(self, user_id: str) -> bool:  # 重置用户策略配置
        """
        重置用户策略配置

        Args:
            user_id: 用户ID

        Returns:
            是否成功
        """  # 方法文档字符串
        try:  # 异常处理
            self._user_configs[user_id] = self._create_default_config(user_id)  # 创建默认配置
            await self._persist_config(user_id, self._user_configs[user_id])  # 持久化
            logger.info(f"[PolicyCenter] 用户 {user_id} 的策略配置已重置")  # 记录日志
            return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[PolicyCenter] 重置用户配置失败: {e}")  # 记录错误
            return False  # 返回失败

    async def get_user_config_summary(self, user_id: str) -> dict[str, Any]:  # 获取用户配置摘要
        """
        获取用户配置摘要

        Args:
            user_id: 用户ID

        Returns:
            配置摘要
        """  # 方法文档字符串
        config = await self.get_user_config(user_id)  # 获取配置
        return {  # 返回摘要
            "user_id": user_id,  # 用户ID
            "allowed_tools_count": len(config.allowed_tools),  # 允许工具数
            "blocked_tools_count": len(config.blocked_tools),  # 阻止工具数
            "custom_risk_levels_count": len(config.custom_risk_levels),  # 自定义风险等级数
            "require_confirmation_count": len(config.require_confirmation_for),  # 需要确认数
            "auto_confirm_threshold": config.auto_confirm_threshold,  # 自动确认阈值
            "allowed_tools": list(config.allowed_tools),  # 允许工具列表
            "blocked_tools": list(config.blocked_tools),  # 阻止工具列表
            "updated_at": config.updated_at.isoformat()  # 更新时间
        }

    # ========== 兼容旧接口 ==========

    async def check_tool(self, tool_id: str, source: str = "user") -> tuple[bool, str]:  # 兼容旧接口
        """兼容旧接口的检查方法（使用默认用户）"""  # 方法文档字符串
        return await self.check_tool_allowed("default", tool_id, source)  # 调用新方法


# 全局实例
policy_center = PolicyCenter()  # 创建全局单例


async def check_tool_allowed(  # 便捷函数：检查工具是否允许
    tool_id: str,
    source: str = "user",
    user_id: str = "default",
    auto_loop_config: dict = None
) -> tuple[bool, str]:  # 返回是否允许及原因
    """便捷函数：检查工具是否允许"""  # 函数文档字符串
    return await policy_center.check_tool_allowed(user_id, tool_id, source, auto_loop_config)  # 调用方法


async def add_user_tool_whitelist(user_id: str, tool_name: str):  # 便捷函数：添加用户工具白名单
    """便捷函数：添加用户工具白名单"""  # 函数文档字符串
    await policy_center.add_user_allowed_tool(user_id, tool_name)  # 调用方法


async def add_user_tool_blacklist(user_id: str, tool_name: str):  # 便捷函数：添加用户工具黑名单
    """便捷函数：添加用户工具黑名单"""  # 函数文档字符串
    await policy_center.add_user_blocked_tool(user_id, tool_name)  # 调用方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"安全策略中心"，负责管理工具访问控制、
# 风险分级和用户级策略配置，确保系统安全运行。
#
# 【主要功能】
# 1. 风险分级：工具按LOW/MEDIUM/HIGH/CRITICAL分级
# 2. 用户策略：支持每个用户独立的工具白名单/黑名单
# 3. 系统保护：保护系统路径和关键进程不被操作
# 4. 确认机制：高危操作需要用户确认
# 5. 自动降级：自动任务禁止执行高风险工具
# 6. 配置持久化：用户策略保存到记忆系统
#
# 【关联文件】
# - core/risk_level.py            : 风险等级枚举定义
# - core/memory.py                : 记忆系统，持久化用户配置
# - core/auto_loop.py             : 自动任务循环，使用本模块过滤风险
# - core/config.py                : 配置模块，提供风险映射和关键词
#
# 【安全检查流程】
# 1. 系统保留工具检查（跳过用户策略）
# 2. 用户阻止列表检查
# 3. 用户允许列表检查（如果配置了白名单）
# 4. 默认策略检查
# 5. 自动任务风险过滤
# 6. 确认需求检查
#
# 【核心功能效果】
# 1. 多租户隔离：每个用户有独立的策略配置
# 2. 系统安全：保护关键系统资源
# 3. 灵活配置：支持白名单、黑名单、自定义风险等级
# 4. 自动化安全：自动任务默认禁止高风险操作
#
# 【使用场景】
# - 工具执行前调用check_tool_allowed()进行权限检查
# - 用户通过界面管理自己的工具白名单
# - 系统管理员设置全局阻止的危险工具
# =============================================================================
