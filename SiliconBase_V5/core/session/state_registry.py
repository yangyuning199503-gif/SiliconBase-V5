#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
状态容器注册表  # 模块功能概述

为前端监控面板提供统一的状态数据源  # 模块用途
各模块主动注册自己的状态访问器，便于统一管理和监控  # 设计理念

设计原则：  # 设计原则说明
1. 不破坏原有状态容器，只添加注册机制  # 原则1
2. 只读访问，不修改原始状态  # 原则2
3. 支持实时监控和状态导出  # 原则3
"""  # 文档字符串结束

import threading  # 导入线程模块
import time  # 导入时间模块
from collections.abc import Callable  # 导入类型注解
from dataclasses import dataclass, field  # 导入数据类装饰器
from datetime import datetime  # 导入日期时间类
from typing import Any, Optional


@dataclass  # 数据类装饰器
class StateContainerInfo:  # 状态容器信息数据类
    """状态容器信息"""  # 类文档字符串
    name: str  # 容器名称
    description: str  # 容器描述
    accessor: Callable[[], dict[str, Any]]  # 状态访问器函数
    last_updated: float = field(default_factory=time.time)  # 最后更新时间，默认当前时间
    update_count: int = 0  # 更新计数，默认0


class StateRegistry:  # 状态注册表类
    """
    状态容器注册表  # 类文档字符串

    单例模式，全局统一管理所有状态容器  # 类职责
    """

    _instance: Optional['StateRegistry'] = None  # 单例实例，类变量
    _lock = threading.Lock()  # 单例锁，类变量

    def __new__(cls):  # 单例控制方法
        if cls._instance is None:  # 如果实例不存在
            with cls._lock:  # 获取锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回单例实例

    def __init__(self):  # 初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回，避免重复初始化

        self._containers: dict[str, StateContainerInfo] = {}  # 状态容器字典
        self._registry_lock = threading.RLock()  # 注册表操作锁
        self._initialized = True  # 标记已初始化

        print("[StateRegistry] 状态注册表初始化完成")  # 打印初始化完成信息

    def register(self, name: str, accessor: Callable[[], dict[str, Any]],
                 description: str = "") -> bool:  # 注册状态容器方法
        """
        注册状态容器  # 方法功能

        Args:  # 参数说明
            name: 状态容器名称（唯一标识）  # 参数1
            accessor: 状态访问器函数，返回状态字典  # 参数2
            description: 状态容器描述  # 参数3

        Returns:  # 返回值说明
            bool: 注册成功返回True，已存在返回False  # 返回类型
        """
        with self._registry_lock:  # 获取锁，保证线程安全
            if name in self._containers:  # 检查是否已存在
                print(f"[StateRegistry] 状态容器 '{name}' 已存在，跳过注册")  # 打印提示
                return False  # 返回失败

            self._containers[name] = StateContainerInfo(  # 创建并保存容器信息
                name=name,  # 名称
                description=description,  # 描述
                accessor=accessor  # 访问器函数
            )

            print(f"[StateRegistry] 状态容器 '{name}' 注册成功")  # 打印成功信息
            return True  # 返回成功

    def unregister(self, name: str) -> bool:  # 注销状态容器方法
        """注销状态容器"""  # 方法文档字符串
        with self._registry_lock:  # 获取锁
            if name not in self._containers:  # 不存在
                return False  # 返回失败

            del self._containers[name]  # 删除容器
            print(f"[StateRegistry] 状态容器 '{name}' 已注销")  # 打印注销信息
            return True  # 返回成功

    def get_state(self, name: str) -> dict[str, Any] | None:  # 获取状态方法
        """
        获取指定状态容器的当前状态  # 方法功能

        Args:  # 参数说明
            name: 状态容器名称  # 参数

        Returns:  # 返回值说明
            Dict: 状态字典，如果不存在返回None  # 返回类型
        """
        with self._registry_lock:  # 获取锁
            container = self._containers.get(name)  # 获取容器
            if not container:  # 不存在
                return None  # 返回None

            try:  # 异常处理
                state = container.accessor()  # 调用访问器获取状态
                container.last_updated = time.time()  # 更新最后更新时间
                container.update_count += 1  # 增加更新计数
                return state  # 返回状态
            except Exception as e:  # 捕获异常
                print(f"[StateRegistry] 获取状态 '{name}' 失败: {e}")  # 打印错误
                return {"error": str(e)}  # 返回错误信息

    def get_all_states(self) -> dict[str, dict[str, Any]]:  # 获取所有状态方法
        """
        获取所有状态容器的当前状态  # 方法功能

        Returns:  # 返回值说明
            Dict: {容器名: 状态字典}  # 返回类型
        """
        with self._registry_lock:  # 获取锁
            states = {}  # 初始化状态字典
            for name, container in self._containers.items():  # 遍历所有容器
                try:  # 异常处理
                    states[name] = container.accessor()  # 获取状态
                    container.last_updated = time.time()  # 更新时间
                    container.update_count += 1  # 增加计数
                except Exception as e:  # 捕获异常
                    states[name] = {"error": str(e)}  # 保存错误信息

            return states  # 返回所有状态

    def get_registry_info(self) -> dict[str, Any]:  # 获取注册表信息方法
        """获取注册表信息（用于监控面板）"""  # 方法文档字符串
        with self._registry_lock:  # 获取锁
            return {  # 返回信息字典
                "registered_containers": [  # 已注册容器列表
                    {
                        "name": c.name,  # 名称
                        "description": c.description,  # 描述
                        "last_updated": datetime.fromtimestamp(c.last_updated).isoformat(),  # ISO格式时间
                        "update_count": c.update_count  # 更新次数
                    }
                    for c in self._containers.values()  # 遍历容器
                ],
                "container_count": len(self._containers),  # 容器数量
                "timestamp": datetime.now().isoformat()  # 当前时间
            }

    def list_containers(self) -> list[str]:  # 列出所有容器方法
        """列出所有已注册的状态容器名称"""  # 方法文档字符串
        with self._registry_lock:  # 获取锁
            return list(self._containers.keys())  # 返回名称列表


# 便捷函数
def get_state_registry() -> StateRegistry:  # 获取状态注册表函数
    """获取状态注册表单例"""  # 函数文档字符串
    return StateRegistry()  # 返回单例实例


def register_state(name: str, accessor: Callable[[], dict[str, Any]],
                   description: str = "") -> bool:  # 便捷注册函数
    """便捷注册函数"""  # 函数文档字符串
    return get_state_registry().register(name, accessor, description)  # 调用注册方法


def get_monitoring_data() -> dict[str, Any]:  # 获取监控数据函数
    """
    获取监控数据（供前端监控面板使用）  # 函数功能

    Returns:  # 返回值说明
        Dict: 完整的监控数据  # 返回类型
    """
    registry = get_state_registry()  # 获取注册表

    return {  # 返回监控数据
        "registry_info": registry.get_registry_info(),  # 注册表信息
        "states": registry.get_all_states(),  # 所有状态
        "timestamp": datetime.now().isoformat()  # 时间戳
    }


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"状态容器注册表"，为前端监控面板提供统一的数据源。
# 各模块主动注册自己的状态访问器，便于统一管理和监控。
#
# 【设计原则】
# 1. 不破坏原有状态容器，只添加注册机制
# 2. 只读访问，不修改原始状态
# 3. 支持实时监控和状态导出
#
# 【核心功能】
# 1. 状态注册：各模块注册状态访问器函数
# 2. 状态查询：获取指定或所有状态容器的当前状态
# 3. 监控数据：生成完整的监控数据供前端使用
# 4. 注册表信息：获取已注册容器的基本信息
#
# 【使用方式】
# - 注册状态：register_state(name, accessor, description)
# - 获取状态：get_state_registry().get_state(name)
# - 监控数据：get_monitoring_data()
#
# 【关联文件】
# - core/global_state.py: 注册全局状态
# - 各业务模块：注册各自的状态访问器
# - 前端监控面板：调用get_monitoring_data()获取数据
# =============================================================================
