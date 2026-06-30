#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
【硅基生命核心】道德系统 - 检查操作是否符合规则  # 模块标题和功能概述
"""  # 文档字符串结束
import threading  # 导入线程模块，用于实现单例模式的线程安全
from dataclasses import dataclass  # 导入数据类装饰器


@dataclass  # 数据类装饰器，自动生成__init__等方法
class MoralCheckResult:  # 道德检查结果数据类
    allowed: bool  # 是否允许执行
    reason: str  # 检查原因/说明
    violated_rules: list[str]  # 违反的规则列表
    suggestion: str  # 改进建议


class MoralGuard:  # 道德守卫类（单例模式）
    _instance = None  # 类变量：单例实例引用
    _lock = threading.Lock()  # 类变量：线程锁，保证线程安全

    def __new__(cls):  # 重写new方法实现单例
        if cls._instance is None:  # 如果实例不存在
            with cls._lock:  # 获取锁
                # 双重检查锁定  # 防止多线程竞争
                if cls._instance is None:  # 再次检查
                    cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回实例

    def __init__(self):  # 构造函数
        if not hasattr(self, '_initialized'):  # 检查是否已初始化（防止重复初始化）
            self._initialized = True  # 标记已初始化
            self.violation_count = 0  # 违规计数器
            self.blocked_actions = []  # 被阻止的操作列表
            self.rules = [  # 核心道德规则列表
                "不伤害自身",  # 规则1：防止自我伤害
                "优先保核心",  # 规则2：保护核心系统
                "禁止高危操作"  # 规则3：禁止危险操作
            ]  # 规则列表结束

    def check_action(self, action_type: str, action_params: dict) -> MoralCheckResult:  # 检查动作
        violated = []  # 违规规则列表
        # 规则1：不伤害自身 - 防止关闭Ollama、删除核心文件等  # 规则1检查
        if self._is_self_harming(action_type, action_params):  # 检查是否自我伤害
            violated.append("不伤害自身")  # 添加到违规列表
        # 规则2：优先保核心 - 核心文件保护  # 规则2检查
        if self._is_core_threat(action_type, action_params):  # 检查是否威胁核心
            violated.append("优先保核心")  # 添加到违规列表
        # 规则3：高危关键词  # 规则3检查
        if self._contains_dangerous_keywords(action_type, action_params):  # 检查危险关键词
            violated.append("禁止高危操作")  # 添加到违规列表

        if violated:  # 如果有违规
            self.violation_count += 1  # 违规计数+1
            self.blocked_actions.append({  # 记录被阻止的操作
                "action_type": action_type,  # 动作类型
                "params": action_params,  # 动作参数
                "rules": violated,  # 违反的规则
                "timestamp": __import__('datetime').datetime.now().isoformat()  # 时间戳
            })  # 记录结束
            return MoralCheckResult(  # 返回不允许结果
                allowed=False,  # 不允许
                reason=f"违反道德规则: {', '.join(violated)}",  # 原因说明
                violated_rules=violated,  # 违规规则列表
                suggestion="请使用安全方式实现"  # 建议
            )  # 返回结束
        return MoralCheckResult(True, "符合道德规则", [], "")  # 返回允许结果

    def _is_self_harming(self, action_type: str, params: dict) -> bool:  # 检查自我伤害
        # 检查是否删除核心文件  # 检查逻辑
        if action_type in ("file_delete", "process_kill"):  # 如果是删除或结束进程
            path = params.get("path", "")  # 获取路径参数
            if any(x in path for x in ["main.py", "core", "config"]):  # 如果涉及核心文件
                return True  # 返回True表示违规
        return False  # 无违规返回False

    def _is_core_threat(self, action_type: str, params: dict) -> bool:  # 检查核心威胁
        if action_type in ("file_write", "file_move"):  # 如果是写入或移动文件
            path = params.get("path", "")  # 获取路径参数
            if any(x in path for x in ["core/", "config/"]):  # 如果涉及核心目录
                return True  # 返回True表示违规
        return False  # 无违规返回False

    def _contains_dangerous_keywords(self, action_type: str, params: dict) -> bool:  # 检查危险关键词
        if action_type in ("execute_command",):  # 如果是执行命令
            cmd = params.get("command", "")  # 获取命令参数
            if "rm -rf" in cmd or "format" in cmd:  # 如果包含危险命令
                return True  # 返回True表示违规
        return False  # 无违规返回False

    def get_stats(self) -> dict:  # 获取统计信息
        return {  # 返回统计字典
            "violation_count": self.violation_count,  # 违规次数
            "blocked_count": len(self.blocked_actions),  # 被阻止次数
            "recent": self.blocked_actions[-5:]  # 最近5次被阻止的操作
        }  # 返回结束


def get_moral_guard() -> MoralGuard:  # 获取道德守卫实例
    return MoralGuard()  # 返回单例实例


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：道德系统模块，负责AI系统的道德规则检查和自我约束  # 角色说明
# 核心功能：  # 功能列表
#   1. 自我伤害防护 - 防止删除核心文件、关闭关键进程等  # 功能1
#   2. 核心系统保护 - 保护core/和config/目录不被修改  # 功能2
#   3. 危险命令拦截 - 拦截rm -rf、format等高危命令  # 功能3
# 设计模式：单例模式（线程安全），确保全局唯一实例  # 设计说明
# 关联文件：  # 关联说明
#   - core/value_system.py: 价值评估（引用道德检查结果）  # 关联1
#   - core/value_system_v2.py: V2价值评估（引用道德统计）  # 关联2
#   - core/safety_guard.py: 安全守卫（更细粒度的安全控制）  # 关联3
#   - core/ast_security_checker.py: AST代码安全检查  # 关联4
# 道德规则：  # 规则说明
#   - 不伤害自身：防止关闭Ollama、删除main.py等核心文件  # 规则1
#   - 优先保核心：保护core/和config/目录不被非法修改  # 规则2
#   - 禁止高危操作：拦截rm -rf、format等系统危险命令  # 规则3
# 达到效果：  # 效果说明
#   - AI具备自我保护的道德意识  # 效果1
#   - 防止意外或恶意操作破坏系统  # 效果2
#   - 为上层安全系统提供道德层面的检查  # 效果3
# =============================================================================  # 分隔线结束
