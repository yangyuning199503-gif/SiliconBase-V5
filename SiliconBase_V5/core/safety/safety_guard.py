#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
【安全守卫 V5.1】动态风险评估系统 - 用户级安全策略学习
核心功能：
- 用户安全画像管理（UserSafetyProfile）
- 动态风险评估（基于用户历史）
- 用户习惯自动学习
- 事故记录与谨慎度调整

【与记忆系统集成】
- L3层存储用户安全画像
- 自动持久化到用户分片存储
"""  # 模块文档字符串：说明本模块的核心功能和记忆系统集成方式
import contextlib
import json  # JSON模块：用于序列化和反序列化用户画像数据
import time  # 时间模块：用于时间戳记录（当前未直接使用）
from dataclasses import dataclass, field  # dataclass装饰器和工具函数
from datetime import datetime  # datetime类：用于记录用户画像更新时间
from typing import Any  # 类型注解：支持复杂类型定义

from core.logger import logger  # 日志记录器：记录安全事件和调试信息
from core.safety.risk_level import RiskLevel  # 风险等级枚举：定义SAFE/NOTICE/CONFIRM/BLOCK等级
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线


@dataclass  # 使用@dataclass自动生成__init__、__repr__等方法
class RiskAssessment:  # 风险评估结果类：封装单次风险评估的输出
    """风险评估结果"""  # 类文档字符串
    level: RiskLevel  # 风险等级：SAFE/NOTICE/CONFIRM/BLOCK之一
    reason: str  # 风险评估原因：说明为何给出该风险等级
    wait_seconds: int = 0  # 等待秒数：执行前需要等待的时间，用于给用户思考时间
    require_double_confirm: bool = False  # 是否需要双重确认：高风险操作时要求两次确认
    requires_confirmation: bool = False  # 兼容性属性：旧接口使用，标记是否需要确认

    def __post_init__(self):  # 初始化后处理方法：dataclass特性，在__init__后自动调用
        """初始化后设置 requires_confirmation"""  # 方法文档字符串
        self.requires_confirmation = self.level in [RiskLevel.NOTICE, RiskLevel.CONFIRM]  # NOTICE和CONFIRM级别需要确认


@dataclass  # 使用@dataclass简化类定义
class UserSafetyProfile:  # 用户安全画像类：存储用户级的安全策略和习惯
    """用户安全画像 - 用户级安全策略学习"""  # 类文档字符串
    user_id: str  # 用户ID：唯一标识用户
    confirmed_operations: dict[str, int] = field(default_factory=dict)  # 操作确认计数：工具名->确认次数，用于学习用户习惯
    accident_history: list[dict] = field(default_factory=list)  # 事故记录列表：存储历史错误信息，用于提高谨慎度
    risk_threshold_adjustment: float = 0.0  # 风险阈值调整：-1到1之间，正值表示更谨慎，负值表示更放心
    trusted_tools: set[str] = field(default_factory=set)  # 用户信任的工具集合：确认多次后加入，可享受风险降级
    blocked_tools: set[str] = field(default_factory=set)  # 用户阻止的工具集合：用户拒绝过的工具
    last_updated: datetime = field(default_factory=datetime.now)  # 最后更新时间：用于判断数据新鲜度

    def to_dict(self) -> dict[str, Any]:  # 转换为字典方法：用于序列化存储
        """转换为字典（用于序列化）"""  # 方法文档字符串
        return {  # 返回包含所有字段的字典，集合转为列表便于JSON序列化
            "user_id": self.user_id,
            "confirmed_operations": self.confirmed_operations,
            "accident_history": self.accident_history,
            "risk_threshold_adjustment": self.risk_threshold_adjustment,
            "trusted_tools": list(self.trusted_tools),  # 将集合转换为列表（JSON不支持集合）
            "blocked_tools": list(self.blocked_tools),  # 将集合转换为列表
            "last_updated": self.last_updated.isoformat()  # 将datetime转换为ISO格式字符串
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict[str, Any]) -> "UserSafetyProfile":  # 从字典创建实例方法
        """从字典创建"""  # 方法文档字符串
        profile = cls(  # 创建新实例
            user_id=data.get("user_id", ""),  # 获取用户ID，默认为空字符串
            confirmed_operations=data.get("confirmed_operations", {}),  # 获取确认操作计数
            accident_history=data.get("accident_history", []),  # 获取事故历史
            risk_threshold_adjustment=data.get("risk_threshold_adjustment", 0.0),  # 获取阈值调整值
            trusted_tools=set(data.get("trusted_tools", [])),  # 将列表转换回集合
            blocked_tools=set(data.get("blocked_tools", [])),  # 将列表转换回集合
            last_updated=datetime.fromisoformat(data.get("last_updated", datetime.now().isoformat()))  # 解析ISO格式时间
        )
        return profile  # 返回创建的实例


class SafetyGuard:  # 安全守卫类：核心安全风险评估引擎
    """
    增强版安全守卫（支持用户习惯学习）
    【核心功能】
    - 用户安全画像管理
    - 动态风险评估
    - 事故记录与学习
    """  # 类文档字符串

    # 通用红线（对所有人都是高风险）：涉及资金、密码、系统安全的操作，不可被用户信任覆盖
    UNIVERSAL_HIGH_RISK = {
        # 钱相关
        "payment", "转账", "支付宝", "微信钱包", "银行",
        "password", "密码", "secret", "密钥", "api_key", "token",
        # 系统关键
        "format", "格式化", "rm -rf /", "del /f/s/q", "format c:",
        "regedit", "注册表", "system32", "boot.ini",
    }

    # 通用中风险（需要提醒但不一定确认）：文件操作、系统控制类操作
    UNIVERSAL_MEDIUM_RISK = {
        "delete", "删除", "remove", "移除", "del ", "rm ",
        "kill", "结束进程", "shutdown", "关机", "reboot", "重启",
        "format", "write", "写入", "modify", "修改",
    }

    # 工具固有风险等级映射：预定义各工具的基础风险等级
    TOOL_RISK_LEVELS = {
        # 文件操作类工具
        "file_read": RiskLevel.SAFE,  # 文件读取：安全
        "file_write": RiskLevel.NOTICE,  # 文件写入：需提醒
        "file_delete": RiskLevel.CONFIRM,  # 文件删除：需确认
        "directory_delete": RiskLevel.CONFIRM,  # 目录删除：需确认
        "directory_list": RiskLevel.SAFE,  # 目录列表：安全

        # 系统操作类工具
        "shell_execute": RiskLevel.CONFIRM,  # Shell执行：需确认
        "process_kill": RiskLevel.CONFIRM,  # 结束进程：需确认
        "system_shutdown": RiskLevel.BLOCK,  # 系统关机：禁止
        "registry_edit": RiskLevel.BLOCK,  # 注册表编辑：禁止

        # 网络操作类工具
        "http_request": RiskLevel.SAFE,  # HTTP请求：安全
        "network_scan": RiskLevel.NOTICE,  # 网络扫描：需提醒
        "download_file": RiskLevel.NOTICE,  # 文件下载：需提醒

        # 敏感操作类工具
        "database_write": RiskLevel.CONFIRM,  # 数据库写入：需确认
        "credential_access": RiskLevel.BLOCK,  # 凭据访问：禁止
        "payment_process": RiskLevel.BLOCK,  # 支付处理：禁止
    }

    # 确认3次后加入信任列表：用户多次确认后可享受风险降级
    TRUST_THRESHOLD = 3
    # 确认5次后风险降级：更多次确认后可进一步降低风险等级
    CONFIRM_DOWNGRADE_THRESHOLD = 5

    def __init__(self):  # 初始化方法
        self._user_profiles: dict[str, UserSafetyProfile] = {}  # 用户画像缓存字典：内存中缓存已加载的用户画像
        self._lock = False  # 简单锁标志：防止并发修改（当前未使用完整锁机制）

        logger.info("[SafetyGuard] 增强版安全守卫初始化完成")  # 记录初始化完成日志

    def _serialize_profile(self, profile: UserSafetyProfile) -> dict[str, Any]:  # 序列化用户画像方法
        """序列化用户画像"""  # 方法文档字符串
        return profile.to_dict()  # 调用UserSafetyProfile的to_dict方法

    def _deserialize_profile(self, data: dict[str, Any]) -> UserSafetyProfile:  # 反序列化用户画像方法
        """反序列化用户画像"""  # 方法文档字符串
        return UserSafetyProfile.from_dict(data)  # 调用UserSafetyProfile的from_dict类方法

    async def get_user_profile(self, user_id: str) -> UserSafetyProfile:  # 获取用户画像方法
        """
        获取或创建用户安全画像
        Args:
            user_id: 用户唯一标识
        Returns:
            用户安全画像
        """  # 方法文档字符串
        if user_id not in self._user_profiles:  # 检查缓存中是否已存在
            # 尝试从记忆恢复
            try:  # 异常处理块
                from core.memory.memory_service import get_memory_service
                memory_service = await get_memory_service()

                stored = await memory_service.query_memories(
                    user_id=user_id,
                    layer="L3",
                    mem_type="safety_profile",
                    limit=1,
                )

                if stored and len(stored) > 0:  # 如果查询到数据
                    content = stored[0].get("content", {})  # 获取内容
                    if isinstance(content, dict) and "profile" in content:  # 检查格式是否正确
                        self._user_profiles[user_id] = self._deserialize_profile(content["profile"])  # 反序列化并缓存
                        logger.debug(f"[SafetyGuard] 从记忆恢复用户 {user_id} 的安全画像")  # 记录恢复日志
                    else:  # 格式不正确
                        self._user_profiles[user_id] = await self._create_default_profile(user_id)  # 创建默认画像
                else:  # 未查询到数据
                    self._user_profiles[user_id] = await self._create_default_profile(user_id)  # 创建默认画像
            except Exception as e:  # 捕获所有异常
                logger.warning(f"[SafetyGuard] 从记忆恢复用户画像失败: {e}")  # 记录警告
                self._user_profiles[user_id] = await self._create_default_profile(user_id)  # 创建默认画像

        return self._user_profiles[user_id]  # 返回用户画像（从缓存或新创建）

    async def _create_default_profile(self, user_id: str) -> UserSafetyProfile:  # 创建默认用户画像方法
        """创建默认用户画像"""  # 方法文档字符串
        return UserSafetyProfile(  # 返回全新的默认画像
            user_id=user_id,
            confirmed_operations={},  # 空确认记录
            accident_history=[],  # 无事故记录
            risk_threshold_adjustment=0.0,  # 中性阈值
            trusted_tools=set(),  # 无信任工具
            blocked_tools=set(),  # 无阻止工具
            last_updated=datetime.now()  # 当前时间
        )

    async def _get_tool_risk_level(self, tool_name: str) -> RiskLevel:  # 获取工具固有风险等级方法
        """获取工具固有风险等级"""  # 方法文档字符串
        # 精确匹配
        if tool_name in self.TOOL_RISK_LEVELS:  # 检查工具是否在预定义映射中
            return self.TOOL_RISK_LEVELS[tool_name]  # 返回对应风险等级

        # 模糊匹配（前缀）：支持工具名前缀匹配
        for tool_pattern, risk in self.TOOL_RISK_LEVELS.items():  # 遍历所有预定义工具
            if tool_name.startswith(tool_pattern) or tool_pattern in tool_name:  # 前缀匹配或包含匹配
                return risk  # 返回匹配的风险等级

        # 默认低风险：未知工具默认LOW级别，减少误拦截
        return RiskLevel.LOW

    async def assess_risk(  # 动态风险评估方法：核心安全评估逻辑
            self,
            user_id: str,  # 用户ID：用于获取用户画像
            tool_name: str,  # 工具名称：评估对象
            params: dict | None = None,  # 工具参数：用于内容风险检测
            context: dict | None = None  # 执行上下文：可用于扩展评估
    ) -> RiskAssessment:  # 返回风险评估结果
        """
        动态风险评估（用户级）
        考虑因素：
        1. 工具固有风险等级
        2. 用户历史确认次数
        3. 用户信任/阻止列表
        4. 用户风险阈值调整
        5. 上下文（如工作目录）
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            params: 工具参数
            context: 执行上下文
        Returns:
            风险评估结果
        """  # 方法文档字符串
        params = params or {}  # 参数默认为空字典
        context = context or {}  # 上下文默认为空字典
        _assessment_result = None  # 【ExperienceBus】用于finally块捕获结果

        try:
            profile = await self.get_user_profile(user_id)  # 获取用户安全画像

            # 处理tool_name可能是字典的情况
            if isinstance(tool_name, dict):
                tool_name = tool_name.get('tool') or tool_name.get('name') or str(tool_name)

            content = f"{tool_name} {json.dumps(params, ensure_ascii=False)}".lower()  # 构建内容字符串用于风险检测，转小写便于匹配

            # 1. 检查通用红线（最高优先级，不受用户信任影响）：涉及资金、密码、系统安全
            if any(risk in content for risk in self.UNIVERSAL_HIGH_RISK):  # 检查是否包含高风险关键词
                # 但如果是用户多次确认过的工具，降级为CONFIRM而非BLOCK
                if tool_name in profile.trusted_tools and len(profile.accident_history) < 3:  # 信任且事故少
                    _assessment_result = RiskAssessment(  # 返回降级后的评估结果
                        level=RiskLevel.CONFIRM,
                        reason="涉及资金、密码或系统安全（但工具在信任列表中）",
                        wait_seconds=10,
                        require_double_confirm=True
                    )
                    return _assessment_result
                _assessment_result = RiskAssessment(  # 返回禁止执行
                    level=RiskLevel.BLOCK,
                    reason="涉及资金、密码或系统安全，禁止执行",
                    wait_seconds=0,
                    require_double_confirm=False
                )
                return _assessment_result

            # 2. 检查用户阻止列表：用户明确拒绝过的工具
            if tool_name in profile.blocked_tools:  # 检查工具是否在阻止列表
                _assessment_result = RiskAssessment(  # 返回禁止执行
                    level=RiskLevel.BLOCK,
                    reason=f"工具 {tool_name} 在用户的阻止列表中",
                    wait_seconds=0,
                    require_double_confirm=False
                )
                return _assessment_result

            # 3. 基础风险等级：从工具预设获取
            base_risk = await self._get_tool_risk_level(tool_name)  # 获取工具固有风险等级
            reason_parts = [f"工具 {tool_name} 的基础风险等级为 {base_risk.value}"]  # 构建原因列表

            # 4. 用户信任列表调整：信任工具可享受风险降级
            if tool_name in profile.trusted_tools:  # 检查工具是否在信任列表
                # 信任工具风险降级（但不能低于SAFE）
                if base_risk == RiskLevel.CONFIRM:  # CONFIRM降级为NOTICE
                    base_risk = RiskLevel.NOTICE
                elif base_risk == RiskLevel.NOTICE:  # NOTICE降级为SAFE
                    base_risk = RiskLevel.SAFE
                reason_parts.append("工具在用户信任列表中，风险已降级")  # 记录降级原因

            # 5. 历史确认次数影响：多次确认可享受风险降级
            confirm_count = profile.confirmed_operations.get(tool_name, 0)  # 获取该工具的确认次数
            if confirm_count >= self.CONFIRM_DOWNGRADE_THRESHOLD and base_risk == RiskLevel.CONFIRM:  # 检查是否达到降级阈值且当前为CONFIRM
                base_risk = RiskLevel.NOTICE  # CONFIRM降级为NOTICE
                reason_parts.append(f"用户已确认 {confirm_count} 次，风险降级")  # 记录降级原因

            # 6. 检查通用中风险关键词：删除、修改等操作
            if any(risk in content for risk in self.UNIVERSAL_MEDIUM_RISK) and base_risk == RiskLevel.SAFE:  # 检查是否包含中风险关键词且当前为SAFE
                base_risk = RiskLevel.NOTICE  # SAFE升级为NOTICE
                reason_parts.append("涉及文件或系统操作关键词")  # 记录升级原因

            # 7. 用户风险阈值调整：根据事故历史调整谨慎度
            adjustment = profile.risk_threshold_adjustment  # 获取阈值调整值
            if adjustment > 0.5:  # 用户变得谨慎（事故多）
                if base_risk == RiskLevel.SAFE:  # SAFE升级为NOTICE
                    base_risk = RiskLevel.NOTICE
                    reason_parts.append("用户近期发生过事故，提高谨慎度")  # 记录调整原因
            elif adjustment < -0.3 and base_risk == RiskLevel.NOTICE:  # 用户很放心且当前为NOTICE
                base_risk = RiskLevel.SAFE  # NOTICE降级为SAFE
                reason_parts.append("用户信任度高，风险降级")  # 记录降级原因

            # 8. 计算等待时间和确认要求：根据最终风险等级确定
            if base_risk == RiskLevel.SAFE:  # 安全级别：无需等待和确认
                wait_seconds = 0
                require_double_confirm = False
            elif base_risk == RiskLevel.NOTICE:  # 提醒级别：短暂等待
                wait_seconds = max(0, 2 - confirm_count // 3)  # 确认越多，等待越短（每3次确认减少1秒）
                require_double_confirm = False
            elif base_risk == RiskLevel.CONFIRM:  # 确认级别：较长等待，可能需要双重确认
                wait_seconds = max(3, 10 - confirm_count)  # 确认越多，等待越短（每次确认减少1秒，最少3秒）
                require_double_confirm = confirm_count < 3  # 确认少于3次需要双重确认
            else:  # BLOCK级别：无需等待（直接禁止）
                wait_seconds = 0
                require_double_confirm = False

            _assessment_result = RiskAssessment(  # 返回最终评估结果
                level=base_risk,
                reason="；".join(reason_parts),  # 用分号连接所有原因
                wait_seconds=wait_seconds,
                require_double_confirm=require_double_confirm
            )
            return _assessment_result

        finally:
            # 【ExperienceBus】安全评估事件（任何return路径都会触发）
            if _assessment_result:
                with contextlib.suppress(Exception):
                    event_bus.emit("safety:assessment", {
                        "user_id": user_id,
                        "tool_name": tool_name,
                        "risk_level": _assessment_result.level.value,
                        "reason": _assessment_result.reason,
                        "timestamp": time.time(),
                    })

    async def record_confirmation(self, user_id: str, tool_name: str, confirmed: bool):  # 记录用户确认行为方法
        """
        记录用户确认行为（用于学习）
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            confirmed: 是否确认执行
        """  # 方法文档字符串
        profile = await self.get_user_profile(user_id)  # 获取用户画像

        if confirmed:  # 用户确认执行
            # 增加确认计数
            profile.confirmed_operations[tool_name] = \
                profile.confirmed_operations.get(tool_name, 0) + 1  # 该工具确认计数+1

            current_count = profile.confirmed_operations[tool_name]  # 获取当前确认次数

            # 多次确认后加入信任列表
            if current_count >= self.TRUST_THRESHOLD:  # 检查是否达到信任阈值（3次）
                profile.trusted_tools.add(tool_name)  # 添加到信任列表
                logger.info(f"[SafetyGuard] 工具 {tool_name} 已加入用户 {user_id} 的信任列表（确认{current_count}次）")  # 记录日志

            # 如果之前阻止过，从阻止列表移除
            if tool_name in profile.blocked_tools:  # 检查是否在阻止列表
                profile.blocked_tools.discard(tool_name)  # 从阻止列表移除
                logger.info(f"[SafetyGuard] 工具 {tool_name} 从用户 {user_id} 的阻止列表移除")  # 记录日志
        else:  # 用户拒绝执行
            # 用户拒绝，加入阻止列表
            profile.blocked_tools.add(tool_name)  # 添加到阻止列表
            # 从信任列表移除（如果有）
            profile.trusted_tools.discard(tool_name)  # 从信任列表移除
            # 重置确认计数
            profile.confirmed_operations[tool_name] = 0  # 确认计数清零
            logger.warning(f"[SafetyGuard] 工具 {tool_name} 已加入用户 {user_id} 的阻止列表（用户拒绝）")  # 记录警告

        profile.last_updated = datetime.now()  # 更新修改时间

        # 保存到记忆
        await self._persist_profile(user_id, profile)  # 持久化用户画像
        # 【ExperienceBus】用户确认事件
        with contextlib.suppress(Exception):
            event_bus.emit("safety:confirmation", {
                "user_id": user_id,
                "tool_name": tool_name,
                "confirmed": confirmed,
                "timestamp": time.time(),
            })

    async def record_accident(self, user_id: str, tool_name: str, error: str):  # 记录安全事故方法
        """
        记录安全事故
        Args:
            user_id: 用户ID
            tool_name: 工具名称
            error: 错误描述
        """  # 方法文档字符串
        profile = await self.get_user_profile(user_id)  # 获取用户画像

        profile.accident_history.append({  # 添加事故记录到历史
            "tool": tool_name,
            "error": error,
            "timestamp": datetime.now().isoformat()  # ISO格式时间戳
        })

        # 事故后提高谨慎度
        profile.risk_threshold_adjustment = min(1.0, profile.risk_threshold_adjustment + 0.1)  # 每次事故增加0.1，最大1.0

        # 从事故中学习
        if len(profile.accident_history) > 3 and tool_name in profile.trusted_tools:  # 事故过多且工具在信任列表
            profile.trusted_tools.discard(tool_name)  # 从信任列表移除
            logger.warning(f"[SafetyGuard] 用户 {user_id} 事故过多，工具 {tool_name} 从信任列表移除")  # 记录警告

        profile.last_updated = datetime.now()  # 更新修改时间

        # 保存到记忆
        await self._persist_profile(user_id, profile)  # 持久化用户画像

        logger.warning(f"[SafetyGuard] 记录用户 {user_id} 事故: {tool_name} - {error}")  # 记录事故日志
        # 【ExperienceBus】安全事故事件
        with contextlib.suppress(Exception):
            event_bus.emit("safety:accident", {
                "user_id": user_id,
                "tool_name": tool_name,
                "error": error,
                "timestamp": time.time(),
            })

    async def _persist_profile(self, user_id: str, profile: UserSafetyProfile):  # 持久化用户画像方法
        """持久化用户画像到记忆系统"""  # 方法文档字符串
        try:  # 异常处理块
            from core.memory.memory_schema import MemoryMetadata
            from core.memory.memory_service import get_memory_service
            memory_service = await get_memory_service()

            content = {
                "type": "safety_profile",
                "profile": self._serialize_profile(profile)  # 序列化用户画像
            }
            content_json = json.dumps(content, ensure_ascii=False)
            metadata = MemoryMetadata(
                user_id=user_id,
                source="checkpoint",
                content_type="json",
                payload_summary=f"安全画像: {user_id}",
                raw_payload=content_json,
            )

            await memory_service.save_memory(
                user_id=user_id,
                layer="L3",
                mem_type="safety_profile",
                content=content_json,
                metadata=metadata,
                scene=f"safety_profile_{user_id}",
                rating=8,
                expire_days=365,
            )
        except Exception as e:  # 捕获所有异常
            logger.error(f"[SafetyGuard] 保存用户画像失败: {e}")  # 记录错误

    async def reset_user_profile(self, user_id: str) -> bool:  # 重置用户安全画像方法
        """
        重置用户安全画像
        Args:
            user_id: 用户ID
        Returns:
            是否成功
        """  # 方法文档字符串
        try:  # 异常处理块
            self._user_profiles[user_id] = await self._create_default_profile(user_id)  # 创建新的默认画像
            await self._persist_profile(user_id, self._user_profiles[user_id])  # 持久化新画像（覆盖旧数据）
            logger.info(f"[SafetyGuard] 用户 {user_id} 的安全画像已重置")  # 记录日志
            return True  # 返回成功
        except Exception as e:  # 捕获所有异常
            logger.error(f"[SafetyGuard] 重置用户画像失败: {e}")  # 记录错误
            return False  # 返回失败

    async def get_profile_stats(self, user_id: str) -> dict[str, Any]:  # 获取用户画像统计方法
        """
        获取用户画像统计
        Args:
            user_id: 用户ID
        Returns:
            统计信息
        """  # 方法文档字符串
        profile = await self.get_user_profile(user_id)  # 获取用户画像
        return {  # 返回统计字典
            "user_id": user_id,
            "confirmed_operations_count": len(profile.confirmed_operations),  # 已确认的操作类型数
            "total_confirmations": sum(profile.confirmed_operations.values()),  # 总确认次数
            "trusted_tools_count": len(profile.trusted_tools),  # 信任工具数量
            "blocked_tools_count": len(profile.blocked_tools),  # 阻止工具数量
            "accident_count": len(profile.accident_history),  # 事故次数
            "risk_threshold_adjustment": profile.risk_threshold_adjustment,  # 阈值调整值
            "last_updated": profile.last_updated.isoformat()  # 最后更新时间
        }

    # ========== 兼容旧接口 ==========

    async def assess(self, tool_id: str, params: dict, user_id: str = "default") -> RiskAssessment:  # 兼容旧接口的风险评估方法
        """兼容旧接口的动态风险评估"""  # 方法文档字符串
        return await self.assess_risk(user_id, tool_id, params, {})  # 调用新接口，context设为空字典

    async def _had_accident_here(self, tool_id: str, params: dict, user_id: str) -> bool:  # 检查是否在此工具上发生过事故（兼容旧接口）
        """检查用户是否在这里翻过车（兼容旧接口）"""  # 方法文档字符串
        profile = await self.get_user_profile(user_id)  # 获取用户画像

        # 检查是否有这个工具的事故记录
        return any(accident.get("tool") == tool_id for accident in profile.accident_history)  # 未匹配到，返回False

    async def _is_user_habit(self, tool_id: str, user_id: str) -> bool:  # 检查是否是用户常用操作（兼容旧接口）
        """检查是否是用户常用操作（兼容旧接口）"""  # 方法文档字符串
        profile = await self.get_user_profile(user_id)  # 获取用户画像
        confirm_count = profile.confirmed_operations.get(tool_id, 0)  # 获取确认次数
        return confirm_count >= self.TRUST_THRESHOLD  # 确认次数达到阈值则认为是习惯


# 全局实例
safety_guard = SafetyGuard()  # 创建模块级单例实例，供全系统使用


async def assess_operation_risk(user_id: str, tool_name: str, params: dict = None, context: dict = None) -> RiskAssessment:  # 评估操作风险便捷函数
    """便捷函数：评估操作风险（新接口）"""  # 函数文档字符串
    return await safety_guard.assess_risk(user_id, tool_name, params, context)  # 调用SafetyGuard实例的方法


async def assess_risk_legacy(tool_id: str, params: dict, user_id: str = "default") -> RiskAssessment:  # 兼容旧接口的便捷函数
    """兼容旧接口的便捷函数"""  # 函数文档字符串
    return await safety_guard.assess(tool_id, params, user_id)  # 调用SafetyGuard实例的兼容方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"安全守卫"模块，负责动态风险评估和用户级安全策略学习。
# 通过用户安全画像（UserSafetyProfile）实现个性化安全防护，平衡安全性与用户体验。
#
# 【架构设计】
# - RiskAssessment: 风险评估结果封装，包含风险等级、原因、等待时间、双重确认要求
# - UserSafetyProfile: 用户安全画像，包含信任列表、阻止列表、事故历史、确认计数
# - SafetyGuard: 核心安全引擎，实现8层风险评估逻辑
# - 持久化机制: 通过L3层记忆系统长期保存用户画像（365天）
#
# 【风险评估8层逻辑】
# 1. 通用红线检测: 资金/密码/系统安全相关操作，最高优先级
# 2. 用户阻止列表: 用户明确拒绝过的工具
# 3. 工具固有风险: 预定义工具风险等级映射
# 4. 信任列表降级: 信任工具可享受风险降级
# 5. 历史确认降级: 5次以上确认可进一步降级
# 6. 中风险关键词: 删除/修改等操作升级风险
# 7. 阈值调整: 根据事故历史调整谨慎度（±0.1~1.0）
# 8. 等待时间计算: SAFE(0s)/NOTICE(0-2s)/CONFIRM(3-10s)/BLOCK(0s)
#
# 【关联文件】
# - core/risk_level.py       : 风险等级枚举定义（SAFE/NOTICE/CONFIRM/BLOCK）
# - core/memory.py           : 记忆管理器，用于持久化用户画像到L3层
# - core/logger.py           : 日志记录器，记录安全事件
# - core/agent_loop.py       : 调用方，在工具执行前调用assess_risk()评估
# - core/tool_executor.py    : 执行后调用record_confirmation()或record_accident()
#
# 【核心功能效果】
# 1. 个性化安全: 基于用户习惯动态调整风险等级，常用工具无需反复确认
# 2. 红线保护: 资金/密码/系统安全操作不可被用户信任覆盖，确保底线安全
# 3. 事故学习: 记录安全事故并自动提高谨慎度，避免重复犯错
# 4. 信任积累: 3次确认加入信任列表，5次确认享受风险降级，正向激励用户
# 5. 阻止机制: 用户拒绝的工具加入阻止列表，尊重用户选择
# 6. 持久化记忆: 用户画像保存365天，跨会话保持一致的安全策略
#
# 【数据流向】
# 输入：工具名+参数+用户ID → assess_risk() → 8层评估逻辑 → RiskAssessment
# 学习：用户确认/拒绝 → record_confirmation() → 更新画像 → _persist_profile()
# 事故：执行错误 → record_accident() → 调整阈值 → 可能移除信任
# 恢复：get_user_profile() → 查询L3记忆 → 反序列化 → 缓存到内存
#
# 【使用场景】
# 场景1: 工具执行前 → assess_risk() → BLOCK则禁止/CONFIRM则等待用户确认/NOTICE仅提醒/SAFE直接执行
# 场景2: 用户确认后 → record_confirmation(..., True) → 计数+1 → 达到阈值加入信任列表
# 场景3: 用户拒绝后 → record_confirmation(..., False) → 加入阻止列表 → 重置计数
# 场景4: 执行出错 → record_accident() → 调整阈值+0.1 → 事故多则移除信任
# 场景5: 系统重启 → get_user_profile() → 从L3记忆恢复画像 → 保持安全策略连续性
# =============================================================================
